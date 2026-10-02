import {StrictMode,Component,type ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import {Home} from './pages/home/Home';
import {Measurements} from './pages/measurements/Measurements';
import {ComparisonPage,HistoricalExperiment} from './pages/simulator/Comparison';
import {SavedResults} from './pages/simulator/SavedResults';
import './styles.css';
class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return{failed:true};}render(){return this.state.failed?<main><h1>화면을 불러오지 못했습니다.</h1><p>페이지를 다시 불러오면 저장된 작업을 확인할 수 있습니다.</p><button onClick={()=>location.reload()}>다시 불러오기</button></main>:this.props.children;}}
function App(){const path=location.pathname.replace(/\/$/,'')||'/';return <ErrorBoundary><a href="#main" className="skip-link">본문으로 건너뛰기</a><header className="topbar"><a href="/" className="brand">CTFM-CIM</a><nav aria-label="주 탐색"><a href="/" aria-current={path==='/'?'page':undefined}>홈</a><a href="/measurements" aria-current={path==='/measurements'?'page':undefined}>측정 데이터 분석</a><a href="/simulator" aria-current={path==='/simulator'?'page':undefined}>CIM 시뮬레이션</a><a href="/saved-results" aria-current={path==='/saved-results'?'page':undefined}>저장한 결과</a></nav></header><main id="main">{path==='/'?<Home/>:path==='/measurements'?<Measurements/>:path==='/simulator'?(new URLSearchParams(location.search).get('experiment')?<HistoricalExperiment id={new URLSearchParams(location.search).get('experiment')!}/>:<ComparisonPage/>):path==='/saved-results'?<SavedResults/>:<><h1>페이지를 찾을 수 없습니다.</h1><a href="/">홈으로 돌아가기</a></>}</main><footer>CTFM-CIM · 측정값, 계산값, 가정을 구분해 표시합니다</footer></ErrorBoundary>;}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
