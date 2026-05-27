// Minimal markdown renderer scoped to the rubric's actual content:
//   headings (h1–h3), blockquotes, bold inline, pipe tables,
//   fenced code blocks, unordered lists, ordered lists, paragraphs.
//
// This is NOT a general markdown library. It handles exactly what rubric_v2.md
// uses and nothing more. Keeping it here avoids a dependency on a third-party
// library while still making the rubric legible.

import React from "react";

type Block =
  | { type: "h1" | "h2" | "h3"; text: string }
  | { type: "blockquote"; lines: string[] }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "code"; lang: string; lines: string[] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "para"; text: string }
  | { type: "hr" };

// Render inline markdown: **bold**, `code`.
function InlineText({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  // Split on **bold** and `code` spans.
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
    } else {
      parts.push(
        <code
          key={key++}
          className="bg-bg-raised text-accent font-mono text-[12px] px-1 rounded"
        >
          {token.slice(1, -1)}
        </code>
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function parseBlocks(md: string): Block[] {
  const lines = md.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Blank line — skip
    if (line.trim() === "") { i++; continue; }

    // HR
    if (/^---+$/.test(line.trim())) { blocks.push({ type: "hr" }); i++; continue; }

    // Headings
    const h1 = line.match(/^# (.+)/);
    if (h1) { blocks.push({ type: "h1", text: h1[1] }); i++; continue; }
    const h2 = line.match(/^## (.+)/);
    if (h2) { blocks.push({ type: "h2", text: h2[1] }); i++; continue; }
    const h3 = line.match(/^### (.+)/);
    if (h3) { blocks.push({ type: "h3", text: h3[1] }); i++; continue; }

    // Blockquote
    if (line.startsWith(">")) {
      const bqLines: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) {
        bqLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", lines: bqLines });
      continue;
    }

    // Fenced code block
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      i++;
      const codeLines: string[] = [];
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // consume closing ```
      blocks.push({ type: "code", lang, lines: codeLines });
      continue;
    }

    // Pipe table: line starts with |
    if (line.startsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      // Row 0 = header, row 1 = separator (skip), rows 2+ = data
      const parseRow = (l: string) =>
        l.split("|").slice(1, -1).map((c) => c.trim());
      const header = parseRow(tableLines[0]);
      const rows = tableLines.slice(2).map(parseRow);
      blocks.push({ type: "table", header, rows });
      continue;
    }

    // Unordered list
    if (/^[-*] /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(lines[i].replace(/^[-*] /, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Ordered list
    if (/^\d+\. /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\. /, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Paragraph: accumulate lines until blank or block-level element
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].startsWith("#") &&
      !lines[i].startsWith(">") &&
      !lines[i].startsWith("```") &&
      !lines[i].startsWith("|") &&
      !/^[-*] /.test(lines[i]) &&
      !/^\d+\. /.test(lines[i]) &&
      !/^---+$/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "para", text: paraLines.join(" ") });
    }
  }

  return blocks;
}

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "h1":
      return (
        <h1 className="text-xl font-semibold text-fg mt-6 mb-2">
          <InlineText text={block.text} />
        </h1>
      );
    case "h2":
      return (
        <h2 className="text-base font-semibold text-fg mt-6 mb-2 border-b border-border pb-1">
          <InlineText text={block.text} />
        </h2>
      );
    case "h3":
      return (
        <h3 className="text-sm font-semibold text-fg mt-4 mb-1">
          <InlineText text={block.text} />
        </h3>
      );
    case "blockquote":
      return (
        <blockquote className="border-l-2 border-accent/50 pl-4 my-3 text-fg-muted text-sm italic">
          {block.lines.map((l, i) => (
            <p key={i}>
              <InlineText text={l} />
            </p>
          ))}
        </blockquote>
      );
    case "code":
      return (
        <pre className="my-3 bg-bg-raised border border-border rounded p-4 text-[12px] font-mono text-fg leading-relaxed overflow-x-auto whitespace-pre">
          {block.lines.join("\n")}
        </pre>
      );
    case "table":
      return (
        <div className="my-3 overflow-x-auto">
          <table className="w-full text-sm border border-border rounded-md overflow-hidden">
            <thead className="bg-bg-raised text-fg-muted text-xs uppercase tracking-wider">
              <tr>
                {block.header.map((h, i) => (
                  <th key={i} className="px-4 py-2 text-left">
                    <InlineText text={h} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri} className="border-t border-border">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-4 py-2 text-fg-muted">
                      <InlineText text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "ul":
      return (
        <ul className="my-2 ml-4 space-y-1 list-disc list-outside text-sm text-fg-muted">
          {block.items.map((item, i) => (
            <li key={i}>
              <InlineText text={item} />
            </li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol className="my-2 ml-4 space-y-1 list-decimal list-outside text-sm text-fg-muted">
          {block.items.map((item, i) => (
            <li key={i}>
              <InlineText text={item} />
            </li>
          ))}
        </ol>
      );
    case "para":
      return (
        <p className="my-2 text-sm text-fg-muted leading-relaxed">
          <InlineText text={block.text} />
        </p>
      );
    case "hr":
      return <hr className="my-4 border-border" />;
  }
}

export function MarkdownRubric({ markdown }: { markdown: string }) {
  const blocks = parseBlocks(markdown);
  return (
    <div className="prose-rubric">
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} />
      ))}
    </div>
  );
}
