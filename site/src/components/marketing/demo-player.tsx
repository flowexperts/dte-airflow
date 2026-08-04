"use client";

import { useCallback, useEffect, useRef, useState } from "react";

function fmt(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export function DemoPlayer() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const [isFs, setIsFs] = useState(false);
  const [showControls, setShowControls] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const revealControls = useCallback(() => {
    setShowControls(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setShowControls(false), 2200);
  }, []);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onMeta = () => setDuration(v.duration);
    const onTime = () => {
      if (!scrubbing) {
        setCurrentTime(v.currentTime);
        setProgress(v.duration ? v.currentTime / v.duration : 0);
      }
    };
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("timeupdate", onTime);
    return () => { v.removeEventListener("loadedmetadata", onMeta); v.removeEventListener("timeupdate", onTime); };
  }, [scrubbing]);

  useEffect(() => {
    const onFsChange = () => setIsFs(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); }
    else { v.pause(); setPlaying(false); }
    revealControls();
  };

  const seek = (e: React.PointerEvent<HTMLDivElement>) => {
    const bar = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - bar.left) / bar.width));
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = ratio * v.duration;
    setProgress(ratio);
    setCurrentTime(ratio * v.duration);
  };

  const onBarPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    setScrubbing(true);
    e.currentTarget.setPointerCapture(e.pointerId);
    seek(e);
  };
  const onBarPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!scrubbing) return;
    seek(e);
    revealControls();
  };
  const onBarPointerUp = () => setScrubbing(false);

  const toggleFs = () => {
    const el = containerRef.current;
    if (!el) return;
    if (!document.fullscreenElement) el.requestFullscreen();
    else document.exitFullscreen();
  };

  return (
    <div
      ref={containerRef}
      className="dplayer"
      onMouseMove={revealControls}
      onMouseLeave={() => { if (hideTimer.current) clearTimeout(hideTimer.current); setShowControls(false); }}
      onTouchStart={revealControls}
    >
      <video
        ref={videoRef}
        className="dplayer-video"
        autoPlay
        muted
        loop
        playsInline
        preload="metadata"
        poster="/marketing/dte-demo-poster.png"
        onClick={togglePlay}
      >
        <source src="/marketing/dte-demo.mp4" type="video/mp4" />
        <source src="/marketing/dte-demo.webm" type="video/webm" />
      </video>

      <div className={`dplayer-controls ${showControls ? "visible" : ""}`}>
        <div
          className="dplayer-bar-track"
          onPointerDown={onBarPointerDown}
          onPointerMove={onBarPointerMove}
          onPointerUp={onBarPointerUp}
        >
          <div className="dplayer-bar-fill" style={{ width: `${progress * 100}%` }} />
          <div className="dplayer-bar-thumb" style={{ left: `${progress * 100}%` }} />
        </div>

        <div className="dplayer-row">
          <button className="dplayer-btn" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
            {playing
              ? <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><rect x="2" y="1" width="4" height="12" rx="1"/><rect x="8" y="1" width="4" height="12" rx="1"/></svg>
              : <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M3 1.5l9 5.5-9 5.5V1.5z"/></svg>
            }
          </button>

          <span className="dplayer-time">
            {fmt(currentTime)}{duration ? ` / ${fmt(duration)}` : ""}
          </span>

          <button className="dplayer-btn dplayer-fs" onClick={toggleFs} aria-label={isFs ? "Exit fullscreen" : "Fullscreen"}>
            {isFs
              ? <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M5 2H2v3M9 2h3v3M5 12H2V9M9 12h3V9"/></svg>
              : <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M2 5V2h3M9 2h3v3M2 9v3h3M12 9v3H9"/></svg>
            }
          </button>
        </div>
      </div>
    </div>
  );
}
