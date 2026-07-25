/*
 * Vertex — tiny dependency-free ambient particle network.
 * Respects reduced-motion and pauses when the tab is hidden.
 */
(() => {
  const canvas = document.querySelector("#vertex");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let width = 0, height = 0, scale = 1, points = [], raf = 0;

  function resize() {
    scale = Math.min(devicePixelRatio || 1, 2);
    width = innerWidth;
    height = innerHeight;
    canvas.width = width * scale;
    canvas.height = height * scale;
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    const count = Math.min(52, Math.max(20, Math.floor(width * height / 30000)));
    points = Array.from({length: count}, (_, index) => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - .5) * .12,
      vy: (Math.random() - .5) * .12,
      r: index % 9 === 0 ? 1.6 : .9
    }));
  }

  function frame() {
    ctx.clearRect(0, 0, width, height);
    for (const point of points) {
      if (!reduced) {
        point.x += point.vx;
        point.y += point.vy;
        if (point.x < -20) point.x = width + 20;
        if (point.x > width + 20) point.x = -20;
        if (point.y < -20) point.y = height + 20;
        if (point.y > height + 20) point.y = -20;
      }
    }
    for (let a = 0; a < points.length; a++) {
      for (let b = a + 1; b < points.length; b++) {
        const dx = points[a].x - points[b].x;
        const dy = points[a].y - points[b].y;
        const distance = Math.hypot(dx, dy);
        if (distance < 145) {
          ctx.strokeStyle = `rgba(190,199,185,${(1 - distance / 145) * .055})`;
          ctx.lineWidth = .6;
          ctx.beginPath();
          ctx.moveTo(points[a].x, points[a].y);
          ctx.lineTo(points[b].x, points[b].y);
          ctx.stroke();
        }
      }
    }
    for (const point of points) {
      ctx.fillStyle = point.r > 1 ? "rgba(241,129,45,.35)" : "rgba(215,221,211,.18)";
      ctx.beginPath();
      ctx.arc(point.x, point.y, point.r, 0, Math.PI * 2);
      ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }

  addEventListener("resize", resize, {passive: true});
  document.addEventListener("visibilitychange", () => {
    cancelAnimationFrame(raf);
    if (!document.hidden) frame();
  });
  resize();
  frame();
})();
