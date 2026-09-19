import {StrictMode,Component,type ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import {Home} from './pages/home/Home';
import {Measurements} from './pages/measurements/Measurements';
import {Simulator} from './pages/simulator/Simulator';
import './styles.css';
class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return{failed:true};}render(){return this.state.failed?<main><h1>화면을 불러오지 못했습니다.</h1><p>페이지를 다시 불러오면 저장된 작업을 확인할 수 있습니다.</p><button onClick={()=>location.reload()}>다시 불러오기</button></main>:this.props.children;}}
function App(){const path=location.pathname.replace(/\/$/,'')||'/';return <ErrorBoundary><a href="#main" className="skip-link">본문으로 건너뛰기</a><header className="topbar"><a href="/" className="brand"><span className="brand-mark">C</span><span>CTFM <small>CIM RESEARCH</small></span></a><nav aria-label="주 탐색"><a href="/" aria-current={path==='/'?'page':undefined}>워크스페이스</a><a href="/measurements" aria-current={path==='/measurements'?'page':undefined}>측정 분석</a><a href="/simulator" aria-current={path==='/simulator'?'page':undefined}>CIM 시뮬레이터</a></nav><span className="version">INTERNAL · v1.1</span></header><main id="main">{path==='/'?<Home/>:path==='/measurements'?<Measurements/>:path==='/simulator'?<Simulator/>:<><h1>페이지를 찾을 수 없습니다.</h1><a href="/">워크스페이스로 돌아가기</a></>}</main><footer>CTFM · 측정값, 계산값, 가정을 구분하는 연구 워크스페이스</footer></ErrorBoundary>;}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
