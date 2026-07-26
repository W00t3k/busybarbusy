(() => {
  const canvas = document.getElementById("signalField"), ctx = canvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0, h = 0, nodes = [], pulses = [];
  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2); w = innerWidth; h = innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + "px"; canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.max(18, Math.min(46, Math.round(w * h / 36000)));
    nodes = Array.from({length: count}, (_, i) => ({
      x: Math.random() * w, y: Math.random() * h,
      vx: (Math.random() - .5) * .055, vy: (Math.random() - .5) * .055,
      warm: i % 4 === 0
    }));
  }
  function draw(now = 0) {
    ctx.clearRect(0, 0, w, h);
    for (const n of nodes) {
      if (!reduced) { n.x += n.vx; n.y += n.vy; }
      if (n.x < -20) n.x = w + 20; if (n.x > w + 20) n.x = -20;
      if (n.y < -20) n.y = h + 20; if (n.y > h + 20) n.y = -20;
    }
    for (let a = 0; a < nodes.length; a++) for (let b = a + 1; b < nodes.length; b++) {
      const distance = Math.hypot(nodes[a].x - nodes[b].x, nodes[a].y - nodes[b].y);
      if (distance > 145) continue;
      ctx.strokeStyle = `rgba(115,145,150,${(1-distance/145)*.055})`;
      ctx.lineWidth = .65; ctx.beginPath(); ctx.moveTo(nodes[a].x, nodes[a].y);
      ctx.lineTo(nodes[b].x, nodes[b].y); ctx.stroke();
    }
    for (const n of nodes) {
      ctx.fillStyle = n.warm ? "rgba(255,106,53,.28)" : "rgba(60,231,207,.18)";
      ctx.beginPath(); ctx.arc(n.x, n.y, n.warm ? 1.5 : 1, 0, Math.PI * 2); ctx.fill();
    }
    if (pulses.length < 4 && Math.random() < .003) {
      const n = nodes[Math.floor(Math.random() * nodes.length)];
      pulses.push({x:n.x, y:n.y, born:now, warm:n.warm});
    }
    pulses = pulses.filter(p => now - p.born < 2600);
    for (const p of pulses) {
      const life = (now-p.born)/2600, alpha = Math.sin(life*Math.PI)*.2;
      ctx.strokeStyle = p.warm ? `rgba(255,106,53,${alpha})` : `rgba(60,231,207,${alpha})`;
      ctx.lineWidth = 1;
      for (let ring=1; ring<=3; ring++) {
        ctx.beginPath(); ctx.arc(p.x,p.y,7+ring*10+life*22,Math.PI*1.18,Math.PI*1.82); ctx.stroke();
      }
      ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.arc(p.x,p.y,1.6,0,Math.PI*2);ctx.fill();
    }
    if (!reduced) requestAnimationFrame(draw);
  }
  addEventListener("resize", resize, {passive:true}); resize(); draw();
})();
