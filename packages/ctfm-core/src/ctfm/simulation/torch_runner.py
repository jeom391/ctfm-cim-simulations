"""CPU float32 MLP training and fixed-weight inference with explicit tiled ADC."""
import math
import numpy as np
from ctfm.adapters import make_linear


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


class Network:
    """Bind restored weights once; ADC is owned only by this wrapper."""
    def __init__(self,layers,engine='torch_reference',tile_size=None,bits=None,bounds=None):
        import torch
        self.engine=engine;self.tile_size=tile_size;self.bits=bits;self.bounds=bounds or {}
        self.layers=[]
        for layer in layers:
            weight=torch.as_tensor(layer['weights'],dtype=torch.float32).contiguous()
            bias=torch.as_tensor(layer['bias'],dtype=torch.float32).contiguous()
            if not torch.isfinite(weight).all() or not torch.isfinite(bias).all():raise ValueError('Nonfinite restored float32 weights/bias')
            item=dict(name=layer['name'],weight=weight,bias=bias,full=make_linear(weight,engine),blocks=[])
            if tile_size is not None:
                for col in range(0,weight.shape[0],tile_size):
                    for row in range(0,weight.shape[1],tile_size):
                        block=weight[col:col+tile_size,row:row+tile_size]
                        item['blocks'].append((col,row,make_linear(block,engine)))
            self.layers.append(item)
        self.reset_stats()

    def reset_stats(self):
        self.stats={layer['name']:dict(count=0,clipped_count=0,clip_abs_error_sum=0.,quantization_abs_error_sum=0.) for layer in self.layers}

    def __call__(self,x,*,calibration=None,record_inputs=None):
        """``record_inputs`` collects each layer's input, which is what the PPA
        engine needs as its activation trace; capturing it here avoids a second
        forward implementation that could drift from this one."""
        import torch
        for i,layer in enumerate(self.layers):
            name=layer['name'];bound=self.bounds.get(name)
            if record_inputs is not None:record_inputs.append(x.detach().cpu().numpy().copy())
            if calibration is not None:
                for col,row,linear in layer['blocks']:
                    partial=linear(x[:,row:row+self.tile_size])
                    calibration[name]=max(calibration.get(name,0.),float(partial.abs().max()))
            if self.bits is None:
                y=layer['full'](x)
            else:
                if bound is None or not math.isfinite(bound) or bound<0:raise ValueError('Missing/invalid validation ADC bound')
                y=torch.zeros((len(x),len(layer['bias'])),dtype=torch.float32)
                diag=self.stats[name];levels=2**self.bits
                for col,row,linear in layer['blocks']:
                    partial=linear(x[:,row:row+self.tile_size])
                    clipped=partial.clamp(-bound,bound)
                    quantized=torch.zeros_like(partial) if bound==0 else -bound+2*bound*torch.floor((clipped+bound)*(levels-1)/(2*bound)+.5)/(levels-1)
                    y[:,col:col+quantized.shape[1]]+=quantized
                    diag['count']+=partial.numel()
                    diag['clipped_count']+=int((partial.abs()>bound).sum())
                    diag['clip_abs_error_sum']+=float((partial-clipped).abs().sum())
                    diag['quantization_abs_error_sum']+=float((quantized-clipped).abs().sum())
            x=y+layer['bias']
            if not torch.isfinite(x).all():raise ValueError('Nonfinite float32 inference output')
            if i<len(self.layers)-1:x=torch.relu(x)
        return x

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
    import torch
    nominal=Network(layers,engine,tile_size=tile_size)
    bounds={layer['name']:0. for layer in layers}
    with torch.inference_mode():
        for x,_ in batches(images,labels,indices):nominal(x,calibration=bounds)
    return bounds
