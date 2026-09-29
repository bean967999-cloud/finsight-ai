export function PagePlaceholder({ title, description }: {
  title: string;
  description: string;
  nextStep: string;
}) {
  return <section className="page-card">
    <h1>{title}</h1>
    <p>{description}</p>
    <p className="muted">此功能暂未开放，不展示模拟结果。</p>
  </section>;
}
