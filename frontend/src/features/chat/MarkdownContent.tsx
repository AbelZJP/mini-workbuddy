import React from "react";

export function renderInlineMarkdown(text: string): React.ReactNode[] {
  const tokenPattern =
    /(`[^`]*`|\*\*[^*]+\*\*|__[^_]+__|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = tokenPattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith("`"))
      nodes.push(<code key={`${match.index}-code`}>{token.slice(1, -1)}</code>);
    else if (token.startsWith("**") || token.startsWith("__"))
      nodes.push(
        <strong key={`${match.index}-strong`}>{token.slice(2, -2)}</strong>,
      );
    else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      nodes.push(
        linkMatch ? (
          <a
            key={`${match.index}-link`}
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer"
          >
            {linkMatch[1]}
          </a>
        ) : (
          token
        ),
      );
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

export function MarkdownContent({ content }: { content: string }) {
  const parts = content.split(/(```[\w-]*\n[\s\S]*?```)/g);
  const renderLines = (
    lines: string[],
    partIndex: number,
  ): React.ReactNode[] => {
    const nodes: React.ReactNode[] = [];
    let lineIndex = 0;
    while (lineIndex < lines.length) {
      const line = lines[lineIndex];
      const nextLine = lines[lineIndex + 1];
      const headerCells = splitMarkdownTableRow(line);
      if (
        nextLine &&
        headerCells.length >= 2 &&
        isMarkdownTableSeparator(nextLine)
      ) {
        const bodyRows: string[][] = [];
        lineIndex += 2;
        while (
          lineIndex < lines.length &&
          lines[lineIndex].trim() &&
          lines[lineIndex].includes("|")
        ) {
          const cells = splitMarkdownTableRow(lines[lineIndex]);
          if (cells.length < 2) break;
          bodyRows.push(cells);
          lineIndex += 1;
        }
        nodes.push(
          <table
            className="markdown-table"
            key={`${partIndex}-table-${lineIndex}`}
          >
            <thead>
              <tr>
                {headerCells.map((cell, cellIndex) => (
                  <th key={cellIndex}>{renderInlineMarkdown(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {headerCells.map((_, cellIndex) => (
                    <td key={cellIndex}>
                      {renderInlineMarkdown(row[cellIndex] || "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>,
        );
        continue;
      }
      const key = `${partIndex}-${lineIndex}`;
      lineIndex += 1;
      if (!line.trim()) {
        nodes.push(<div className="markdown-spacer" key={key} />);
        continue;
      }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        nodes.push(
          React.createElement(
            `h${heading[1].length}`,
            { key },
            ...renderInlineMarkdown(heading[2]),
          ),
        );
        continue;
      }
      if (/^\s*>/.test(line)) {
        nodes.push(
          <blockquote key={key}>
            {renderInlineMarkdown(line.replace(/^\s*>\s?/, ""))}
          </blockquote>,
        );
        continue;
      }
      const bullet = line.match(/^\s*[-*]\s+(.+)$/);
      if (bullet) {
        nodes.push(
          <div className="markdown-list-item" key={key}>
            • <span>{renderInlineMarkdown(bullet[1])}</span>
          </div>,
        );
        continue;
      }
      const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
      if (ordered) {
        nodes.push(
          <div className="markdown-list-item" key={key}>
            • <span>{renderInlineMarkdown(ordered[1])}</span>
          </div>,
        );
        continue;
      }
      nodes.push(<p key={key}>{renderInlineMarkdown(line)}</p>);
    }
    return nodes;
  };
  return (
    <div className="markdown-content">
      {parts.map((part, index) => {
        if (!part) return null;
        if (part.startsWith("```")) {
          const match = part.match(/^```([\w-]*)\n([\s\S]*?)```$/);
          return (
            <pre key={index}>
              <code className={match?.[1] ? `language-${match[1]}` : undefined}>
                {match?.[2] || part.slice(3, -3)}
              </code>
            </pre>
          );
        }
        return renderLines(part.split("\n"), index);
      })}
    </div>
  );
}

export function splitMarkdownTableRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|") && !value.endsWith("\\|")) value = value.slice(0, -1);
  return value
    .split(/(?<!\\)\|/)
    .map((cell) => cell.replace(/\\\|/g, "|").trim());
}

export function isMarkdownTableSeparator(line: string): boolean {
  const cells = splitMarkdownTableRow(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

export function formatToolValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
