> ⚠️ 这是**格式示例**：标题与 2610.24518 的作者机构来自 arXiv 真实数据；
> 8 篇深度解读的「问题 / 方法 / 结果」为示意文本，实际运行时由 DeepSeek 阅读全文后按同一模板生成。

---

# 量子论文雷达 · 2026年10月20日

> QRC · 量子算法（近最优优先）· quant-ph 每日精选

## 今日概览

| 数据源 | 状态 | 数量 |
| --- | --- | --- |
| Scirate quant-ph | ✅ （DeepSeek Fetch） | 10 篇 |
| arXiv quant-ph | ✅ （72h 内） | 99 篇 |
| DeepSeek 搜索 | ✅ （7 组查询） | 28 条 |

新增（未推送过）**11** 篇；候选精读 **30** 篇；LLM 调用 **12** 次。

## 🔥 Scirate 今日热榜

> 按社区 scites 票数排序，代表当天量子领域最受关注的预印本。

1. **[The Fundamental Memory Ceiling of Noisy Quantum Reservoirs](https://arxiv.org/abs/2610.26228)**
   `QRC` · #1 · ⬆ 14 scites · AI 8.4/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 给出噪声下量子储备池记忆容量的理论上界，并给出达到上界的条件。

2. **[Physics-anchored residual quantum neural networks for cloud-cover parameterization](https://arxiv.org/abs/2610.26279)**
   `QRC` · #2 · ⬆ 9 scites · AI 7.2/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 把物理约束嵌入残差量子神经网络，用于云量参数化。

3. **[Supervised Learning with Quantum Hamiltonian Embeddings](https://arxiv.org/abs/2610.26833)**
   `QRC` · #3 · ⬆ 7 scites · AI 7.0/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 用量子哈密顿量嵌入做监督学习，给出表达力与训练成本的分析。

4. **[Exact Quantum Query Complexity of the Five-Bit Symmetric Boolean Function](https://arxiv.org/abs/2610.24518)**
   `量子算法` · #4 · ⬆ 6 scites · AI 9.1/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 紧确界结果，证明三次查询不可能，将精确复杂度确定为 4。

5. **[Quantum algorithms for optimal control: large-scale finite-horizon linear-quadratic regulation](https://arxiv.org/abs/2610.26843)**
   `量子算法` · #5 · ⬆ 5 scites · AI 8.0/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 把量子线性系统算法用于最优控制，给出端到端复杂度与经典 LQR 的对比。

6. **[Efficient Quantum Algorithm for Mixed-State Quantum Geometry](https://arxiv.org/abs/2610.24686)**
   `量子算法` · #6 · ⬆ 4 scites · AI 7.6/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 用量子相位估计加速混合态量子几何张量估计，给出精度与查询复杂度的权衡。

7. **[Measurement-efficient energy estimator for quantum chemistry of photodynamic materials](https://arxiv.org/abs/2610.26689)**
   `量子算法` · #7 · ⬆ 3 scites · AI 7.3/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 降低量子化学能量估计的测量开销，在光动力材料上做了验证。

8. **[Higher-order Parity Constraints for Quantum Approximate Optimization](https://arxiv.org/abs/2610.26381)**
   `量子算法` · #8 · ⬆ 2 scites · AI 7.0/10 · 10-20
   📖 见下方「重点论文深度解读」
   > 💡 在 QAOA 中加入高阶奇偶约束，小规模数值上改善近似比。

## 📖 重点论文深度解读

> 由 DeepSeek 阅读全文后生成的简报：问题、方法、结果三段式，便于判断是否精读。

### QRC（3 篇）

#### 1. The Fundamental Memory Ceiling of Noisy Quantum Reservoirs

**中文标题**：含噪量子储备池的记忆容量上限

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.26228) · [arXiv](https://arxiv.org/abs/2610.26228) · [全文](https://arxiv.org/pdf/2610.26228) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.26228)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

量子储备池的短期记忆容量在噪声下如何衰减？此前缺少理论上界。

**2. 核心方法或创新**

① **记忆容量上界的推导**：把储备池的 fading memory 性质与噪声通道的混合时间联系起来，得到容量上界。

② **数值验证**：在自旋链储备池上验证上界的紧致性。

**3. 值得关注的结果或意义**

① 噪声强度与容量呈反比关系，给出可检验的 scaling；
② 局限：上界对特定噪声模型成立，非马尔可夫噪声待检验。

#### 2. Physics-anchored residual quantum neural networks for cloud-cover parameterization

**中文标题**：物理约束的残差量子神经网络用于云量参数化

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.26279) · [arXiv](https://arxiv.org/abs/2610.26279) · [全文](https://arxiv.org/pdf/2610.26279) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.26279)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

气候模式中的云量参数化难以用经典模型拟合。

**2. 核心方法或创新**

① **物理锚定**：把辐射传输的守恒约束嵌入残差连接。

② **量子线路设计**：用数据重上传编码输入。

**3. 值得关注的结果或意义**

① 在再分析数据上误差低于纯经典基线；
② 局限：仅在离线数据上验证。

#### 3. Supervised Learning with Quantum Hamiltonian Embeddings

**中文标题**：量子哈密顿量嵌入的监督学习

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.26833) · [arXiv](https://arxiv.org/abs/2610.26833) · [全文](https://arxiv.org/pdf/2610.26833) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.26833)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

量子特征映射如何影响监督学习的表达力？

**2. 核心方法或创新**

① **哈密顿量嵌入**：把数据编码为哈密顿量的参数，演化产生特征。

② **表达力分析**：给出嵌入方式与可表示函数类的关系。

**3. 值得关注的结果或意义**

① 在合成数据上优于角度编码；
② 局限：训练成本随体系增大。

### 量子算法（5 篇）

#### 1. Exact Quantum Query Complexity of the Five-Bit Symmetric Boolean Function

**中文标题**：五比特对称布尔函数的精确量子查询复杂度

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Guoliang Xu | — |
| Haoran Zhang | — |
| Mengfan Wu | — |
| Songyao Xue | School of Software；Luoyang Normal University；Luoyang 471934, China |
| Mingke Liu | School of Artificial Intelligence；Luoyang Normal University；Luoyang 471934, China |

**链接**：[SciRate](https://scirate.com/arxiv/2610.24518) · [arXiv](https://arxiv.org/abs/2610.24518) · [全文](https://arxiv.org/pdf/2610.24518) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.24518)

**摘要中文翻译**

设 f 为恰好在海明重量 3 或 4 的输入上取 1 的布尔函数。此前的数值研究报告称三次查询可达到接近 1 的成功概率，但三次查询精确算法是否存在一直悬而未决。本文证明该函数的精确量子查询复杂度为 4。下界方面，用低阶 Fourier 系数的逐层 Gram 矩阵表达任意三查询算法，并构造固定有理对偶证书排除三次查询。

**1. 主要解决的问题**

精确量子查询复杂度 $Q_E(f)$ 要求算法在所有输入上以概率 1 正确。对 $f=\text{EXACT}^{5}_{3,4}$，此前只有数值证据指向「三次查询可能够用」，但既没有算法也没有排除证明——核心在于数值优化找到的高成功概率解是否真能被零误差算法实现。

**2. 核心方法或创新**

① **Fourier–Gram 层分解**：把任意三查询算法按层展开，每一层的振幅用该层所取低阶 Fourier 系数的 Gram 矩阵描述，从而把「是否存在三查询精确算法」转化为关于半正定矩阵的可行性问题，而不是在指数大的算法空间里搜索。

② **有理对偶证书**：构造固定的有理系数对偶证书，对上述半正定可行性给出矛盾。证书固定、可显式验证，不依赖数值求解，因此结论严格——这与仅靠 SDP 数值解得到的证据有本质区别。

③ **SOS 表示处理近似误差**：针对近似误差下界，用平方和表示把对偶证书写成代数恒等式，把「三查询不可能」推广到更一般的误差参数区间。

④ **四次查询上界**：给出显式的四次查询精确算法，与下界匹配。

**3. 值得关注的结果或意义**

① **主结果**：$Q_E(\text{EXACT}^{5}_{3,4}) = 4$，三次查询无论怎么设计都不可能零误差，四次查询足够，终结了一个此前只有数值证据的开放问题。

② **方法论意义**：Fourier–Gram 逐层分解 + 有理对偶证书是一套可复用框架，适用于其他对称函数或低阶 Fourier 结构明显的函数。

③ **局限**：证书是针对该函数具体构造的；上界算法依赖特殊结构，不构成通用算法。

#### 2. Quantum algorithms for optimal control: large-scale finite-horizon linear-quadratic regulation

**中文标题**：量子最优控制：大规模有限时域线性二次调节

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.26843) · [arXiv](https://arxiv.org/abs/2610.26843) · [全文](https://arxiv.org/pdf/2610.26843) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.26843)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

经典 LQR 在状态维度大时计算成本高；能否用量子线性系统算法加速？

**2. 核心方法或创新**

① **量子线性系统求解**：把 Riccati 方程离散化后转化为线性方程组，用量子线性系统算法求解，给出状态维度与精度依赖的复杂度上界。

② **与经典 LQR 对照**：在同一问题族上与经典算法比较端到端复杂度，明确量子优势成立的条件。

**3. 值得关注的结果或意义**

① 在精度与维度的特定区间内给出多项式加速；
② 局限：依赖量子线性系统算法的条件数假设，需要高效的数据输入模型。

#### 3. Efficient Quantum Algorithm for Mixed-State Quantum Geometry

**中文标题**：混合态量子几何张量的高效量子算法

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.24686) · [arXiv](https://arxiv.org/abs/2610.24686) · [全文](https://arxiv.org/pdf/2610.24686) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.24686)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

混合态量子几何张量（量子度规与 Berry 曲率）的经典估计需要大量测量。

**2. 核心方法或创新**

① **量子相位估计**：把几何张量分量写成可观测量的期望，用相位估计与 Hadamard 测试组合估计。

② **测量复用**：设计共享同一组测量的估计方案，降低总采样次数。

**3. 值得关注的结果或意义**

① 给出关于精度 $\epsilon$ 的采样复杂度上界，优于逐项估计；
② 局限：在含噪中等规模设备上的常数开销尚未评估。

#### 4. Measurement-efficient energy estimator for quantum chemistry of photodynamic materials

**中文标题**：光动力材料量子化学的能量估计高效测量方案

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.26689) · [arXiv](https://arxiv.org/abs/2610.26689) · [全文](https://arxiv.org/pdf/2610.26689) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.26689)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

量子化学能量估计中测量开销是主要瓶颈。

**2. 核心方法或创新**

① **分组测量**：利用哈密顿量的对易结构把可观测量分组，减少所需测量次数。

② **误差界**：给出分组方案下的方差与偏差界。

**3. 值得关注的结果或意义**

① 在光动力材料分子上把测量次数降到基线的约三分之一；
② 局限：仅在小分子上验证。

#### 5. Higher-order Parity Constraints for Quantum Approximate Optimization

**中文标题**：QAOA 的高阶奇偶约束

**作者与机构**

| 作者 | 论文署名机构 |
| --- | --- |
| Author A | Some University |
| Author B | — |

**链接**：[SciRate](https://scirate.com/arxiv/2610.26381) · [arXiv](https://arxiv.org/abs/2610.26381) · [全文](https://arxiv.org/pdf/2610.26381) · [arXiv DOI](https://doi.org/10.48550/arXiv.2610.26381)

**摘要中文翻译**

（摘要中文翻译略）

**1. 主要解决的问题**

标准 QAOA 在带约束的组合优化上需要惩罚项，影响解质量。

**2. 核心方法或创新**

① **高阶奇偶约束编码**：把约束直接编码为高阶奇偶项，避免惩罚系数调参。

② **小规模数值验证**：在约束优化实例上与标准 QAOA 比较近似比。

**3. 值得关注的结果或意义**

① 小规模实例上近似比优于标准 QAOA；
② 局限：高阶项的线路实现成本随阶数增长。

---

*由 paper-radar 自动生成 · 生成时间 2026-10-20 09:30 CST*
