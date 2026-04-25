import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  h1: (props) => (
    <h1
      className="mt-2 mb-3 text-xl font-semibold tracking-tight first:mt-0"
      {...props}
    />
  ),
  h2: (props) => (
    <h2
      className="mt-5 mb-2 text-lg font-semibold tracking-tight"
      {...props}
    />
  ),
  h3: (props) => (
    <h3 className="mt-4 mb-2 text-base font-semibold" {...props} />
  ),
  p: (props) => <p className="my-2 leading-7" {...props} />,
  ul: (props) => <ul className="my-2 list-disc space-y-1 pl-6" {...props} />,
  ol: (props) => <ol className="my-2 list-decimal space-y-1 pl-6" {...props} />,
  li: (props) => <li className="leading-6" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  hr: (props) => (
    <hr className="my-4 border-zinc-200 dark:border-zinc-800" {...props} />
  ),
  blockquote: (props) => (
    <blockquote
      className="my-3 border-l-4 border-zinc-300 dark:border-zinc-700 pl-4 italic text-zinc-700 dark:text-zinc-300"
      {...props}
    />
  ),
  code: (props) => (
    <code
      className="rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 text-sm"
      {...props}
    />
  ),
};

export function Synthesis({ markdown }: { markdown: string }) {
  return (
    <div className="text-sm text-zinc-900 dark:text-zinc-100">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
