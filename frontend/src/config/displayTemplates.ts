/** Display template schema — defines how a software's records are rendered into a multi-section analysis page.
 *  Edit this file to change the display; the rendering engine reads it at build time.
 *  Keyed by software code (lowercase, matching backend Software.code). */
export interface MetricCardDef { label: string; metric: string; icon?: string; unit?: string; }
export interface ComparisonColumn { key: string; label: string; desc?: string; }
export interface ComparisonRow { metric: string; label: string; unit?: string; }
export interface DisplaySection {
  type: 'hero' | 'metric_cards' | 'comparison_table' | 'text_block' | 'tag_cloud' | 'data_table';
  title?: string;
  subtitle?: string;
  cards?: MetricCardDef[];
  /** payload field used to group records into comparison columns */
  variantField?: string;
  columns?: ComparisonColumn[];
  rows?: ComparisonRow[];
  content?: string;
  tags?: string[];
}
export interface DisplayTemplate {
  softwareCode: string;
  title: string;
  subtitle?: string;
  heroTags?: string[];
  sections: DisplaySection[];
}

const TEMPLATES: Record<string, DisplayTemplate> = {

  lammps: {
    softwareCode: 'lammps',
    title: 'LAMMPS 性能偏移分析',
    subtitle: 'HPC Performance Offset Analysis',
    heroTags: ['分子动力学', '经典MD', '离子液体电润湿', 'PPPM长程库仑力'],
    sections: [
      {
        type: 'text_block', title: '测试环境',
        content: '**机器**：华中一区 7490 | **内存**：512 GB | **存储**：NAS | **网络**：IB 400 Gb\n**计算类型**：带有长程库仑力计算的离子液体电润湿\n**输入**：Al₂O₃_eam 算例，dimension 2 / boundary p s p / atom_style atomic',
      },
      {
        type: 'metric_cards', title: '1 运行总览',
        cards: [
          { label: 'CPU 浮点计算', metric: 'CPU Time', icon: '▲', unit: 'seconds' },
          { label: 'MPI 通信等待', metric: 'MPI 等待时间', icon: '◄', unit: 'seconds' },
          { label: 'IO 存储读写', metric: 'IO 吞吐峰值', icon: '▽', unit: 'MB/s' },
        ],
      },
      {
        type: 'comparison_table', title: '2 软件优化提升',
        variantField: 'variant',
        columns: [
          { key: 'baseline', label: '基础版', desc: '7490 基准' },
          { key: 'avx2', label: '+AVX2', desc: '指令集优化' },
          { key: 'avx512', label: '+AVX-512', desc: '指令集优化' },
          { key: 'omp', label: '+OMP', desc: '开源包' },
          { key: 'kokkos', label: '+KOKKOS', desc: '开源包' },
          { key: 'mkl', label: '+MKL', desc: '数学库' },
          { key: 'numa', label: '+NUMA', desc: '访存通信' },
        ],
        rows: [
          { metric: 'CPU Time', label: 'CPU 浮点计算时间', unit: 's' },
          { metric: 'MPI 等待时间', label: 'MPI 通信等待时间', unit: 's' },
          { metric: 'IO 吞吐峰值', label: 'IO 吞吐峰值', unit: 'MB/s' },
        ],
      },
      {
        type: 'tag_cloud', title: '3 程序画像',
        tags: ['中高计算密集', '中低通信密集', '低IO密集(IO稀疏)'],
      },
      {
        type: 'text_block', title: '4 优化建议',
        content: '**软件优化**：LAMMPS 调用 PPPM 长程库仑力时 FFTW 占比较高，升级指令集 + KOKKOS-CPU + MKL 后 FFT 时间显著缩短；MPI 通信中 PMPI_AWAIT 无法减少，需减少进程数或调整域分解。\n**硬件选型**：IO 优化在此案例收益甚小；7490 和 8358P 均在发挥 AVX-512 的能力，但 8358P 体现出更强的计算能力。建议工程师关注 AVX-512 与 KOKKOS-CPU；超算建设维持 7490 的 AVX-512 设计。',
      },
      {
        type: 'data_table', title: '5 性能记录明细',
      },
    ],
  },

  vasp: {
    softwareCode: 'vasp',
    title: 'VASP 性能偏移分析',
    subtitle: 'Vienna Ab initio Simulation Package',
    heroTags: ['电子结构', '量子化学', 'DFT计算'],
    sections: [
      { type: 'text_block', title: '状态', content: '该软件的性能偏移分析数据正在整理中，待数据接入后即可展示完整的运行总览、优化提升图表与分析报告。' },
    ],
  },

  gromacs: {
    softwareCode: 'gromacs',
    title: 'GROMACS 性能偏移分析',
    subtitle: 'GROningen MAchine for Chemical Simulations',
    heroTags: ['分子动力学', '生物分子', '膜蛋白'],
    sections: [
      { type: 'text_block', title: '状态', content: '该软件的性能偏移分析数据正在整理中。' },
    ],
  },

  openfoam: {
    softwareCode: 'openfoam',
    title: 'OpenFOAM 性能偏移分析',
    subtitle: 'Computational Fluid Dynamics',
    heroTags: ['计算流体力学', '湍流模拟'],
    sections: [
      { type: 'text_block', title: '状态', content: '该软件的性能偏移分析数据正在整理中。' },
    ],
  },

  cp2k: {
    softwareCode: 'cp2k',
    title: 'CP2K 性能偏移分析',
    subtitle: 'Ab Initio Molecular Dynamics',
    heroTags: ['AIMD', '电子结构', 'DFT'],
    sections: [
      { type: 'text_block', title: '状态', content: '该软件的性能偏移分析数据正在整理中。' },
    ],
  },
};

export function getDisplayTemplate(code: string): DisplayTemplate | null {
  return TEMPLATES[code] ?? null;
}

export function getAllDisplayTemplates(): DisplayTemplate[] {
  return Object.values(TEMPLATES);
}