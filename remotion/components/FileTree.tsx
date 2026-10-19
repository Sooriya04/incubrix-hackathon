import React from 'react';
import { interpolate, useCurrentFrame } from 'remotion';
import { C, FONTS } from '../theme';

interface FileTreeItem {
  name: string;
  isFolder?: boolean;
  annotation?: string;
  depth?: number;
}

interface FileTreeProps {
  items: FileTreeItem[];
  framesPerItem?: number;
  fontSize?: number;
}

export const FileTree: React.FC<FileTreeProps> = ({
  items,
  framesPerItem = 4,
  fontSize = 20,
}) => {
  const frame = useCurrentFrame();

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        fontFamily: FONTS.mono,
        fontSize: `${fontSize}px`,
      }}
    >
      {items.map((item, idx) => {
        const itemStart = idx * framesPerItem;
        const progress = interpolate(frame, [itemStart, itemStart + 4], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });

        if (progress === 0) return null;

        const depth = item.depth || 0;
        const indent = '  '.repeat(depth);

        return (
          <div
            key={idx}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              opacity: progress,
              transform: `translateX(${interpolate(progress, [0, 1], [-8, 0])}px)`,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <span style={{ color: C.line, marginRight: '8px', whiteSpace: 'pre' }}>
                {indent}{item.isFolder ? '▶ ' : '· '}
              </span>
              <span
                style={{
                  color: item.isFolder ? C.accent : C.text,
                  fontWeight: item.isFolder ? 600 : 400,
                }}
              >
                {item.name}
              </span>
            </div>
            {item.annotation && (
              <span
                style={{
                  color: C.muted,
                  fontSize: `${fontSize - 4}px`,
                  marginLeft: '24px',
                }}
              >
                // {item.annotation}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
};
