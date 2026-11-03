import ReactMarkdown, { type Components } from "react-markdown"

// Chat messages are markdown (03 §2.3). Raw HTML is dropped (skipHtml), images are shown
// as their alt text (no third-party fetches), and react-markdown's default urlTransform
// strips unsafe URLs such as `javascript:`.
const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  img: ({ alt }) => <span>{alt}</span>,
}

// No typography plugin in the stack, so the few elements chat replies use are styled here.
const MARKDOWN_STYLES =
  "space-y-2 break-words [&_a]:underline [&_a]:underline-offset-2 [&_code]:rounded [&_code]:bg-black/5 [&_code]:px-1 [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-5"

export function Markdown({ children }: { children: string }) {
  return (
    <div className={MARKDOWN_STYLES}>
      <ReactMarkdown skipHtml components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
