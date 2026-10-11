import './App.css'

function App() {
  return (
    <main className="page">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="AOA home">
          <span className="brand-mark">A</span>
          <span>AOA</span>
        </a>
        <span className="topbar-label">AI Optimization Automation</span>
      </header>

      <section className="hero" id="home">
        <p className="eyebrow">YOUR OPTIMIZATION WORKSPACE</p>
        <h1>Turn ideas into better outcomes.</h1>
        <p className="intro">
          AOA brings optimization workflows and automation together in one place.
          This workspace is ready for your first experiment.
        </p>
        <div className="status"><span /> Starter workspace ready</div>
      </section>

      <section className="stack" aria-label="Project stack">
        <article className="stack-card">
          <span className="card-number">01 / CORE</span>
          <h2>Python</h2>
          <p>Build optimization logic, process data, and run automation.</p>
        </article>
        <article className="stack-card">
          <span className="card-number">02 / INTERFACE</span>
          <h2>TypeScript + React</h2>
          <p>Create the web interface for configuring and reviewing workflows.</p>
        </article>
      </section>

      <footer>AOA <span>·</span> AI Optimization Automation</footer>
    </main>
  )
}

export default App
