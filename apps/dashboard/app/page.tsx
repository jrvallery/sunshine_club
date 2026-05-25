const workflowItems = [
  "NAS corpus intake",
  "Extraction",
  "Classification",
  "Placement resolution",
  "Review or pending Drive action"
];

export default function Page() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 32, maxWidth: 960 }}>
      <h1>Sunshine Club Admin</h1>
      <p>
        V1 focuses on the local corpus organization loop: register staged files,
        classify them, resolve deterministic destinations, and review anything unsafe.
      </p>
      <section>
        <h2>Foundation Workflow</h2>
        <ol>
          {workflowItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      </section>
    </main>
  );
}
