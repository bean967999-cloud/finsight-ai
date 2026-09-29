import type { ReactNode } from "react";
import { generationLabel, type GenerationInfo } from "../Api/Research";

export function TrustNotice({ summary, children, title = "口径与限制说明" }: {
  summary: string; children?: ReactNode; title?: string;
}) {
  return <aside className="trust-notice"><p>{summary}</p>
    {children && <details><summary>{title}</summary><div>{children}</div></details>}
  </aside>;
}

export function AnswerMethod({ generation }: { generation?: GenerationInfo | null }) {
  return <p className="hint">{generationLabel({ generation }) ?? "回答方式：历史结果未记录调用方式，不能据此判断是否调用外部模型。"}</p>;
}

export function RiskGlossary() {
  return <TrustNotice summary="风险指标描述所选历史样本，不构成投资建议，也不保证未来损失上限。" title="金融术语与计算口径">
    <p>VaR：在给定置信水平和持有期下，按历史样本估计的损失分位数；不是最坏损失。</p>
    <p>CVaR：历史尾部损失的平均水平。此处VaR/CVaR以比例表示，不是货币损失。</p>
    <p>波动率衡量收益变化幅度；最大回撤衡量相对历史高点的下降程度；夏普比率比较超额收益与波动。</p>
    <p>Beta衡量收益相对所选基准的敏感度，需要基准数据。未复权价格不等于包含分红的总回报。</p>
  </TrustNotice>;
}
