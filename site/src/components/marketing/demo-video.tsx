"use client";
import { useEffect, useRef } from "react";

/** The demo video: plays (muted) while half of it is on screen, pauses when
 *  scrolled away. Skipped for prefers-reduced-motion. */
export function DemoVideo() {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const v = ref.current;
    if (!v || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(
      ([e]) => (e?.isIntersecting ? v.play().catch(() => {}) : v.pause()),
      { threshold: 0.5 },
    );
    io.observe(v);
    return () => io.disconnect();
  }, []);

  return (
    <video ref={ref} className="video" controls muted playsInline preload="metadata" poster="/demo/dte-airflow-poster.jpg">
      <source src="/demo/dte-airflow.mp4" type="video/mp4" />
      <source src="/demo/dte-airflow.webm" type="video/webm" />
    </video>
  );
}
