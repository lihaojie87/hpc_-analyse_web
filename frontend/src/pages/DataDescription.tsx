import { Link } from 'react-router-dom';

const definitions = [
  ['CPU Time', '进程在 CPU 上消耗的累计时间，单位为秒；它不等同于用户实际等待的墙钟时间。'],
  ['Elapsed Time', '性能分析工具或应用日志记录的经过时间，适合用于表达用户实际等待时长。'],
  ['并行度', '用于判断任务是否有效利用分配的并行资源，应同时展示公式口径，不能直接称为 CPU 利用率。'],
  ['读/写 IOPS 与延迟', 'IOPS 表示每秒操作次数，延迟表示单次操作响应时间，需结合两者判断存储瓶颈。'],
  ['性能提升倍数', '沿用原始测试表提供的提升值，当前页面不重新推算；若补充优化前后耗时，应重新校验口径。'],
  ['CPU / MPI / Overhead', '分别代表计算、通信同步和运行时管理等开销。占比高的模块对应优先诊断方向。'],
];
export default function DataDescription(): JSX.Element {
  return <main className="stack"><div className="page-heading"><div><h1>数据说明</h1><p>统一解释性能画像字段、单位与当前展示口径。</p></div><Link className="button button-secondary" to="/dashboard">返回总览</Link></div><section className="card stack"><h2 className="card-title">指标术语</h2><div className="definition-grid">{definitions.map(([term, description]) => <article className="definition-card" key={term}><h3>{term}</h3><p>{description}</p></article>)}</div></section><section className="card stack"><h2 className="card-title">数据层次</h2><div className="data-layer-grid"><div><strong>对象层</strong><p>用户、机器、软件与算例，回答“谁在什么环境运行什么任务”。</p></div><div><strong>基线层</strong><p>原始耗时、CPU、并行度和 IO，描述未经优化的基线表现。</p></div><div><strong>优化层</strong><p>编译、数学库、绑核、存储和硬件方案带来的性能收益。</p></div><div><strong>诊断层</strong><p>CPU/MPI 热点、输入参数及瓶颈类型，支持后续优化决策。</p></div></div></section><p className="muted">缺失值显示为“—”，不以 0 代替；0 仅在后端明确返回数值 0 时展示。</p></main>;
}
