import { ArrowSquareOut } from "@phosphor-icons/react/dist/ssr";

import type { Post } from "@/lib/types";
import { clockTime } from "@/lib/format";

export default function PostList({ posts }: { posts: Post[] }) {
  if (posts.length === 0) {
    return (
      <p className="border-t border-line py-6 text-[13px] text-faint">
        No posts stored for this window. Stored text is kept on a rolling window;
        counts go back further than the text does.
      </p>
    );
  }

  return (
    <ul className="border-t border-line">
      {posts.map((post) => (
        <li key={`${post.did}-${post.rkey}`} className="border-b border-line py-2.5">
          <div className="flex items-center gap-2">
            <span className="num text-[11px] text-faint">{clockTime(post.ts)}</span>
            {post.lang && (
              <span className="font-mono text-[10px] uppercase text-faint">{post.lang}</span>
            )}
            <a
              href={post.url}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto text-faint transition-colors hover:text-accent"
              aria-label="Open post on Bluesky"
            >
              <ArrowSquareOut size={13} weight="regular" />
            </a>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
            {post.text}
          </p>
        </li>
      ))}
    </ul>
  );
}
