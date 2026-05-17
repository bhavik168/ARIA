import React, { useEffect, useRef } from "react";

interface WaveformProps {
  playing: boolean;
  paused: boolean;
  wordPulses: React.MutableRefObject<Array<{ at: number; idx: number }>>;
}

const BAR_COUNT = 56;

export default function Waveform({ playing, paused, wordPulses }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef({ bars: new Array(BAR_COUNT).fill(0.1) as number[], t: 0 });

  useEffect(() => {
    let raf: number;
    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const w = canvas.width;
      const h = canvas.height;
      const st = stateRef.current;
      st.t += 1;

      // Decay all bars
      for (let i = 0; i < BAR_COUNT; i++) {
        st.bars[i] *= 0.92;
        if (st.bars[i] < 0.05) st.bars[i] = 0.05;
      }

      // Add a moving "playhead" energy if playing
      if (playing) {
        const center = (st.t * 0.6) % BAR_COUNT;
        for (let i = 0; i < BAR_COUNT; i++) {
          const d = Math.abs(i - center);
          if (d < 8) {
            const e = (1 - d / 8) * (0.18 + 0.18 * Math.sin(st.t * 0.15 + i * 0.7));
            st.bars[i] = Math.max(st.bars[i], e);
          }
        }
      }

      // Word burst contributions
      const now = performance.now();
      wordPulses.current = wordPulses.current.filter((p) => now - p.at < 1100);
      for (const p of wordPulses.current) {
        const age = (now - p.at) / 1100;
        const intensity = Math.max(0, 1 - age) * 0.95;
        for (let i = 0; i < BAR_COUNT; i++) {
          const d = Math.abs(i - p.idx);
          if (d < 6) {
            const v = intensity * (1 - d / 6);
            st.bars[i] = Math.max(st.bars[i], v);
          }
        }
      }

      // Render
      ctx.clearRect(0, 0, w, h);
      const barW = w / BAR_COUNT;
      const gap = 2;
      for (let i = 0; i < BAR_COUNT; i++) {
        const v = st.bars[i];
        const barH = Math.max(2, v * h * 0.95);
        const x = i * barW + gap / 2;
        const y = (h - barH) / 2;
        let color: string;
        if (paused) color = "#cbd5e1";
        else if (v > 0.55) color = "#1d4ed8";
        else if (v > 0.25) color = "#2563eb";
        else color = "#bfdbfe";
        ctx.fillStyle = color;
        ctx.fillRect(x, y, barW - gap, barH);
      }

      // Playhead line
      if (playing) {
        const ph = ((st.t * 0.6) % BAR_COUNT) * barW + barW / 2;
        ctx.strokeStyle = "rgba(255,255,255,0.55)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(ph, 4);
        ctx.lineTo(ph, h - 4);
        ctx.stroke();
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [playing, paused, wordPulses]);

  // hi-dpi resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const resize = () => {
      const r = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = r.width * dpr;
      canvas.height = r.height * dpr;
      canvas.style.width = r.width + "px";
      canvas.style.height = r.height + "px";
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.scale(dpr, dpr);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, []);

  return (
    <canvas ref={canvasRef} style={{ width: "100%", height: 56, display: "block" }} />
  );
}
