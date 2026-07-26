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
    if (pulses.length < 11 && Math.random() < .015) {
      const n = nodes[Math.floor(Math.random() * nodes.length)];
      pulses.push({x:n.x, y:n.y, born:now, tone:Math.floor(Math.random() * 3)});
    }
    pulses = pulses.filter(p => now - p.born < 3000);
    for (const p of pulses) {
      const life = (now-p.born)/3000, alpha = Math.sin(life*Math.PI)*.17;
      const rgb = p.tone === 0 ? "255,106,53" : p.tone === 1 ? "244,239,232" : "0,0,0";
      ctx.strokeStyle = `rgba(${rgb},${p.tone === 2 ? alpha * 1.8 : alpha})`;
      ctx.lineWidth = 1;
      for (let ring=1; ring<=4; ring++) {
        ctx.beginPath(); ctx.arc(p.x,p.y,5+ring*9+life*28,Math.PI*1.14,Math.PI*1.86); ctx.stroke();
      }
      const radius = 17 + life * 55, angle = life * Math.PI * 3;
      ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.globalAlpha = .35; ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + Math.cos(angle) * radius, p.y + Math.sin(angle) * radius); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.arc(p.x,p.y,1.6,0,Math.PI*2);ctx.fill();
    }
    if (!reduced) requestAnimationFrame(draw);
  }
  addEventListener("resize", resize, {passive:true}); resize(); draw();
})();
