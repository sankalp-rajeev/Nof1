export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <p className="mb-12 border-l-2 border-teal-700 pl-4 text-sm leading-6 text-stone-600">
        Nof1 is a self-tracking research prototype. It is not medical advice.
      </p>
      <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-teal-800">
        Self-tracking, with context
      </p>
      <h1 className="text-5xl font-semibold tracking-tight sm:text-7xl">Nof1</h1>
      <p className="mt-6 max-w-lg text-lg leading-8 text-stone-600">
        A place to record your day, explore possible patterns, and learn from
        structured personal experiments.
      </p>
      <p className="mt-12 text-sm text-stone-500">
        Development scaffold · Daily check-ins are coming in a later phase.
      </p>
    </main>
  );
}
