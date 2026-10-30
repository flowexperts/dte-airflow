/** The dark band at the top of every page that isn't the landing page. */
export function PageHero({ title, hi, lede }: { title: string; hi: string; lede: string }) {
  return (
    <header className="page-hero">
      <div className="in">
        <h1>{title} <span className="hi">{hi}</span></h1>
        <p className="lede">{lede}</p>
      </div>
    </header>
  );
}
