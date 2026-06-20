"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage } from "@/lib/types";

interface Props {
  message: ChatMessage;
}

// Strip the trailing ```json ... ``` action block from assistant messages before display.
// During streaming the block arrives a token at a time, so we also strip an
// unterminated trailing ```json fence to keep the raw JSON from flashing on screen.
function stripActionBlock(content: string): string {
  return content
    .replace(/```json\s*\{[\s\S]*?"action"\s*:[\s\S]*?\}\s*```/g, "")
    .replace(/```json[\s\S]*$/, "")
    .trim();
}

function GuitarPickIcon() {
  return (
    <svg
      width="18"
      height="22"
      viewBox="0 0 18 22"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="flex-shrink-0"
    >
      <path
        d="M9 1C5.5 1 2 4 2 8C2 12 6 16 9 21C12 16 16 12 16 8C16 4 12.5 1 9 1Z"
        fill="#E8820C"
        stroke="#B85F00"
        strokeWidth="1.2"
      />
    </svg>
  );
}

function TypingIndicator({ label }: { label?: string }) {
  return (
    <div className="flex gap-2 items-center h-5 px-1">
      <div className="flex gap-1 items-center">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-2 h-2 rounded-full bg-[#9A8F78] animate-bounce"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </div>
      {label && (
        <span className="text-xs text-[#9A8F78] italic animate-fade-in">{label}</span>
      )}
    </div>
  );
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const displayContent = isUser ? message.content : stripActionBlock(message.content);
  // Show the typing indicator (optionally with a live status label) while the
  // agent is working and no answer text has streamed in yet.
  const isTyping = message.content === "__typing__" || (!!message.status && !message.content);

  return (
    <div className={`flex gap-2 mb-4 ${isUser ? "justify-end" : "justify-start"} animate-fade-in`}>
      {!isUser && (
        <div className="mt-1 flex-shrink-0">
          <GuitarPickIcon />
        </div>
      )}

      <div
        className={`max-w-[80%] px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "rounded-[18px_18px_4px_18px] bg-[rgba(232,130,12,0.15)] border border-[rgba(232,130,12,0.3)] text-[#F0EAD6]"
            : "rounded-[18px_18px_18px_4px] bg-[#1A1712] border border-[#2E2920] text-[#F0EAD6]"
        }`}
      >
        {isTyping ? (
          <TypingIndicator label={message.status} />
        ) : isUser ? (
          <p className="whitespace-pre-wrap">{displayContent}</p>
        ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h2: ({ children }) => (
                <h2 className="text-[#C9A227] font-semibold text-base mt-3 mb-1 first:mt-0" style={{ fontFamily: "'Playfair Display', serif" }}>
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="text-[#E8820C] font-semibold text-sm mt-2 mb-1">
                  {children}
                </h3>
              ),
              strong: ({ children }) => (
                <strong className="text-[#C9A227] font-semibold">{children}</strong>
              ),
              ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
              li: ({ children }) => <li className="text-[#F0EAD6]">{children}</li>,
              p: ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
              code: ({ children, className }) => {
                const isBlock = className?.includes("language-");
                if (isBlock) return null; // JSON action blocks are stripped; don't render other code blocks as raw
                return (
                  <code className="bg-[#252017] text-[#C9A227] px-1.5 py-0.5 rounded text-xs font-mono">
                    {children}
                  </code>
                );
              },
              pre: () => null, // suppress raw code blocks in chat
            }}
          >
            {displayContent}
          </ReactMarkdown>
        )}
      </div>
    </div>
  );
}
