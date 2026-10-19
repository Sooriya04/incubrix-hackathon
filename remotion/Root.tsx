import React from 'react';
import { Composition } from 'remotion';
import { BrollVideo, BrollVideoProps } from './BrollVideo';
import captionsData from './captions.json';
import { RATIOS, RatioKey } from './ratios';

export const Root: React.FC = () => {
  const duration = captionsData?.totalFrames || 240;

  return (
    <>
      {(Object.keys(RATIOS) as RatioKey[]).map((k) => {
        const cfg = RATIOS[k];

        return (
          <Composition
            key={k}
            id={cfg.id}
            component={BrollVideo as React.FC<any>}
            width={cfg.w}
            height={cfg.h}
            fps={30}
            durationInFrames={duration}
            defaultProps={{
              ratio: k,
              themeName: 'developer',
              captions: captionsData,
              audioSrc: 'voiceover.mp3',
            }}
            calculateMetadata={async ({ props }) => {
              const frames = (props as any)?.captions?.totalFrames || captionsData?.totalFrames || 240;
              return {
                durationInFrames: frames,
              };
            }}
          />
        );
      })}
    </>
  );
};
