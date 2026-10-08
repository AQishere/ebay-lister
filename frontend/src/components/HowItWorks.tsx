const STEPS = [
  {
    title: 'Describe it',
    body: 'Type what you are selling in a few words. "iphone 13" or "jordan 1 chicago size 10" is enough to start.',
  },
  {
    title: 'Tap a few answers',
    body: 'We ask only for what buyers filter by, like storage, size or condition, with answers taken from real listings.',
  },
  {
    title: 'Copy and list',
    body: 'Get a search-ready title, item specifics, a description and a price based on what similar items sell for.',
  },
]

// Fills the landing page until the first draft appears.
export function HowItWorks() {
  return (
    <section className="how" aria-labelledby="how-title">
      <h2 id="how-title" className="eyebrow">
        How it works
      </h2>
      <ol className="how-steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="card how-step">
            <span className="how-num">{i + 1}</span>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}
