"""CPU float32 MLP training and fixed-weight inference with explicit tiled ADC."""
import math
import numpy as np
from ctfm.adapters import make_linear
from .math import INPUT_BITS, INPUT_LEVELS, ADC_ORDERS


def create_model():
    import torch
    return torch.nn.Sequential(torch.nn.Linear(784,128), torch.nn.ReLU(), torch.nn.Linear(128,10)).float().cpu()


def batches(images, labels, indices=None, batch_size=256):
    import torch
    if indices is None: indices = np.arange(len(images))
    for start in range(0,len(indices),batch_size):
        idx=indices[start:start+batch_size]
        x=torch.as_tensor(images[idx],dtype=torch.float32)/255.
        y=torch.as_tensor(labels[idx],dtype=torch.long)
        yield x,y


def train_model(images, labels, train_indices, seed, progress=None):
    import torch
    torch.manual_seed(seed)
    model=create_model();model.train()
    optimizer=torch.optim.Adam(model.parameters(),lr=.001)
    generator=torch.Generator(device='cpu').manual_seed(seed)
    losses=[]
    for epoch in range(5):
        order=train_indices[torch.randperm(len(train_indices),generator=generator).numpy()]
        total=0.;count=0
        for x,y in batches(images,labels,order):
            optimizer.zero_grad(set_to_none=True)
            loss=torch.nn.functional.cross_entropy(model(x),y)
            loss.backward();optimizer.step()
            total+=float(loss.detach())*len(y);count+=len(y)
        losses.append(total/count)
        if progress:progress('training',epoch+1,5)
    model.eval()
    return model,losses


def model_layers(model):
    return [dict(name=name,weights=layer.weight.detach().cpu().numpy().copy(),bias=layer.bias.detach().cpu().numpy().copy())
            for name,layer in [('fc1',model[0]),('fc2',model[2])]]


def _quantize(z, bits, lower, upper):
    """Q from docs/spec/08 section 4, on a uniform grid over [lower, upper]."""
    import torch
    if upper == lower: return torch.zeros_like(z)
    steps = 2**bits-1
    code = torch.floor((z.clamp(lower,upper)-lower)/(upper-lower)*steps+.5).clamp(0,steps)
    return lower+code*(upper-lower)/steps


def input_ranges(layers, images, labels, indices):
    """r per layer from the digital checkpoint: 1 for pixels, validation ReLU max
    for the hidden layer (docs/spec/08 section 4). Test data is never used."""
    import torch
    network=Network(layers)
    ranges={layers[0]['name']:1.}
    recorded=[]
    with torch.inference_mode():
        for x,_ in batches(images,labels,indices):
            captured=[];network(x,record_inputs=captured)
            recorded.append([float(t.max()) for t in captured[1:]])
    for offset,layer in enumerate(layers[1:]):
        ranges[layer['name']]=max((row[offset] for row in recorded),default=0.)
    return ranges


class Network:
    """Bind restored weights once; input quantization and ADC live only here.

    A layer is either digital (``weights``) or mapped onto a measured G+/G- cell
    pair (``g_plus``/``g_minus``/``scale``). Only a mapped layer can carry an
    ADC, because the converter sits on a physical plane's partial sum.
    """
    def __init__(self,layers,engine='torch_reference',*,tile_size=None,bits=None,bounds=None,
                 adc_order=None,input_bits=None):
        import torch
        self.engine=engine;self.tile_size=tile_size;self.bits=bits;self.bounds=bounds or {}
        self.adc_order=adc_order;self.input_bits=input_bits
        if bits is not None:
            if adc_order not in ADC_ORDERS:raise ValueError('ADC requires an explicit order: '+', '.join(ADC_ORDERS))
            if input_bits not in (None,INPUT_BITS):raise ValueError('The ADC path is defined for 8 bit serial input')
            self.input_bits=INPUT_BITS
        if not isinstance(tile_size,(int,type(None))) or isinstance(tile_size,bool) or (tile_size is not None and tile_size<1):
            raise ValueError('Tile size must be a positive integer; it is physical with the ADC off too')
        self.layers=[]
        for layer in layers:
            differential='g_plus' in layer
            if bits is not None and not differential:
                raise ValueError('The ADC is defined on the measured G+/G- planes, not on digital weights')
            planes=[]
            if differential:
                scale=float(layer['scale'])
                weight=torch.as_tensor(scale*(np.asarray(layer['g_plus'])-np.asarray(layer['g_minus'])),dtype=torch.float32)
                for key in ('g_plus','g_minus'):
                    planes.append(torch.as_tensor(np.asarray(layer[key]),dtype=torch.float32).contiguous())
            else:
                scale=1.
                weight=torch.as_tensor(layer['weights'],dtype=torch.float32)
            weight=weight.contiguous()
            bias=torch.as_tensor(layer['bias'],dtype=torch.float32).contiguous()
            if not torch.isfinite(weight).all() or not torch.isfinite(bias).all():raise ValueError('Nonfinite restored float32 weights/bias')
            item=dict(name=layer['name'],weight=weight,bias=bias,scale=scale,
                      input_range=float(layer.get('input_range',1.)),
                      full=make_linear(weight,engine),blocks=[])
            if planes and tile_size is not None:
                for col in range(0,weight.shape[0],tile_size):
                    for row in range(0,weight.shape[1],tile_size):
                        item['blocks'].append((col,row)+tuple(
                            make_linear(plane[col:col+tile_size,row:row+tile_size].contiguous(),engine)
                            for plane in planes))
            self.layers.append(item)
        self.reset_stats()

    def reset_stats(self):
        self.stats={layer['name']:dict(count=0,clipped_count=0,clip_abs_error_sum=0.,quantization_abs_error_sum=0.) for layer in self.layers}

    def _encode(self,x,layer):
        """Unsigned 8 bit input codes and the reconstruction step r/255."""
        import torch
        r=layer['input_range']
        if self.input_bits is None:return None,x,1.
        if float(x.min())<0:raise ValueError('Unsigned 8 bit input encoding requires nonnegative activations')
        if r==0:codes=torch.zeros_like(x)
        else:codes=torch.floor(INPUT_LEVELS*x/r+.5).clamp(0,INPUT_LEVELS)
        step=r/INPUT_LEVELS
        return codes,codes*step,step

    def __call__(self,x,*,calibration=None,record_inputs=None):
        """``record_inputs`` collects each layer's input, which is what the PPA
        engine needs as its activation trace; capturing it here avoids a second
        forward implementation that could drift from this one."""
        import torch
        for i,layer in enumerate(self.layers):
            name=layer['name']
            if record_inputs is not None:record_inputs.append(x.detach().cpu().numpy().copy())
            codes,restored,step=self._encode(x,layer)
            if self.bits is None and calibration is None:
                # Identical sum to the bit serial loop; acceptance 2 checks it.
                y=layer['full'](restored)
            else:
                if codes is None:raise ValueError('The bit serial path requires 8 bit input encoding')
                y=self._serial(layer,codes,step,calibration)
            x=y+layer['bias']
            if not torch.isfinite(x).all():raise ValueError('Nonfinite float32 inference output')
            if i<len(self.layers)-1:x=torch.relu(x)
        return x

    def _serial(self,layer,codes,step,calibration):
        """LSB-first 8 cycle schedule over the two physical planes."""
        import torch
        name=layer['name'];batch=len(codes)
        if not layer['blocks']:raise ValueError('The bit serial path requires a tiled differential layer')
        planes=torch.stack([torch.floor(codes/2**k)%2 for k in range(self.input_bits)])
        significance=(2.**torch.arange(self.input_bits,dtype=torch.float32)).reshape(-1,1,1)
        accumulated=torch.zeros((batch,len(layer['bias'])),dtype=torch.float32)
        diag=self.stats[name];bound=None
        if self.bits is not None:
            bound=(self.bounds.get(name) or {}).get(self.adc_order)
            if bound is None or not math.isfinite(bound) or bound<0:
                raise ValueError('Missing/invalid validation ADC bound for '+name+'/'+str(self.adc_order))
        collected=calibration.setdefault(name,{order:0. for order in ADC_ORDERS}) if calibration is not None else None
        for col,row,plus_linear,minus_linear in layer['blocks']:
            block=planes[:,:,row:row+self.tile_size]
            flat=block.reshape(-1,block.shape[2])
            plus=plus_linear(flat).view(self.input_bits,batch,-1)
            minus=minus_linear(flat).view(self.input_bits,batch,-1)
            if collected is not None:
                collected['subtract_then_adc']=max(collected['subtract_then_adc'],float((plus-minus).abs().max()))
                collected['adc_then_subtract']=max(collected['adc_then_subtract'],float(plus.max()),float(minus.max()))
            if self.bits is None:
                converted=plus-minus
            elif self.adc_order=='subtract_then_adc':
                converted=self._convert(plus-minus,-bound,bound,diag)
            else:
                converted=self._convert(plus,0.,bound,diag)-self._convert(minus,0.,bound,diag)
            accumulated[:,col:col+converted.shape[2]]+=(significance*converted).sum(dim=0)
        return accumulated*step*layer['scale']

    def _convert(self,partial,lower,upper,diag):
        import torch
        clipped=partial.clamp(lower,upper)
        quantized=_quantize(partial,self.bits,lower,upper)
        diag['count']+=partial.numel()
        diag['clipped_count']+=int(((partial<lower)|(partial>upper)).sum())
        diag['clip_abs_error_sum']+=float((partial-clipped).abs().sum())
        diag['quantization_abs_error_sum']+=float((quantized-clipped).abs().sum())
        return quantized

    def diagnostics(self):
        result={}
        for name,s in self.stats.items():
            result[name]={**s,'saturation_ratio':s['clipped_count']/s['count'] if s['count'] else None,
                          'mean_clip_abs_error':s['clip_abs_error_sum']/s['count'] if s['count'] else None,
                          'mean_quantization_abs_error':s['quantization_abs_error_sum']/s['count'] if s['count'] else None}
        return result


def evaluate(network,images,labels,indices=None):
    import torch
    correct=0;count=0;network.reset_stats()
    with torch.inference_mode():
        for x,y in batches(images,labels,indices):
            prediction=network(x).argmax(dim=1)
            correct+=int((prediction==y).sum());count+=len(y)
    if not count:raise ValueError('Cannot evaluate empty dataset')
    return dict(accuracy=correct/count,correct=correct,n=count,adc=network.diagnostics())


def calibrate(layers,images,labels,indices,tile_size,engine):
    """Nominal ADC ranges per layer for both orders, collected with the ADC off.

    One pass covers every tile and bit plane, so the range is shared across bit
    counts, arrays and retention timepoints and never derived from an already
    quantized signal (docs/spec/08 section 4).
    """
    import torch
    nominal=Network(layers,engine,tile_size=tile_size,input_bits=INPUT_BITS)
    bounds={}
    with torch.inference_mode():
        for x,_ in batches(images,labels,indices):nominal(x,calibration=bounds)
    return bounds
