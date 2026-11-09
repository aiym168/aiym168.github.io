(function(){
  function sample(i){
    var side = i%2===0?-1:1;
    var u=Math.sin(i*12.9898)*43758.5453; u-=Math.floor(u);
    var v=Math.sin(i*78.233)*43758.5453; v-=Math.floor(v);
    var th=u*Math.PI, ph=v*Math.PI*2;
    var x=Math.abs(Math.sin(th)*Math.cos(ph)*0.78)*side+side*0.22;
    var y=Math.cos(th)*0.62;
    var z=Math.sin(th)*Math.sin(ph)*0.95;
    return {x:x,y:y,z:z};
  }
  window.mountBrainFallback = function(container){
    if(!container) return;
    var c=document.createElement('canvas');
    Object.assign(c.style,{position:'absolute',inset:'0',width:'100%',height:'100%',display:'block',margin:'0',transform:'none'});
    container.appendChild(c);
    var ctx=c.getContext('2d');
    var mobile=Math.min(innerWidth,innerHeight)<720;
    var N=mobile?220:520;
    var pts=[];
    var cx=0,cy=0,cz=0;
    for(var i=0;i<N;i++){ var p=sample(i); pts.push(p); cx+=p.x; cy+=p.y; cz+=p.z; }
    cx/=N; cy/=N; cz/=N;
    var radius=0;
    for(var i=0;i<N;i++){
      pts[i].x-=cx; pts[i].y-=cy; pts[i].z-=cz;
      radius=Math.max(radius, Math.hypot(pts[i].x,pts[i].y,pts[i].z));
    }
    var t0=performance.now(), mouse={x:0,y:0};
    function resize(){
      var w=container.clientWidth||600, h=container.clientHeight||360;
      var dpr=Math.min(devicePixelRatio||1, 2);
      c.width=w*dpr; c.height=h*dpr;
      c.style.width=w+'px'; c.style.height=h+'px';
      ctx.setTransform(dpr,0,0,dpr,0,0);
    }
    resize();
    if(window.ResizeObserver){ new ResizeObserver(resize).observe(container); }
    else addEventListener('resize', resize);
    addEventListener('pointermove',function(e){
      var r=container.getBoundingClientRect();
      mouse.x=((e.clientX-r.left)/r.width)*2-1;
      mouse.y=((e.clientY-r.top)/r.height)*2-1;
    },{passive:true});
    function project(p,rotY,rotX,w,h){
      var cos=Math.cos(rotY),sin=Math.sin(rotY);
      var x=p.x*cos - p.z*sin;
      var z=p.x*sin + p.z*cos;
      var cosx=Math.cos(rotX),sinx=Math.sin(rotX);
      var y=p.y*cosx - z*sinx;
      z=p.y*sinx + z*cosx;
      // fit sphere into view with ~1.25 margin
      var scale = Math.min(w,h) * 0.42 / Math.max(radius, 0.8);
      return {x:w/2+x*scale, y:h/2-y*scale, z:z};
    }
    function frame(now){
      var t=(now-t0)/1000;
      var w=container.clientWidth||600, h=container.clientHeight||360;
      ctx.clearRect(0,0,w,h);
      var rotY=t*0.2+mouse.x*0.4, rotX=mouse.y*0.2;
      var proj=[];
      for(var i=0;i<pts.length;i++) proj.push(project(pts[i],rotY,rotX,w,h));
      for(var i=0;i<proj.length;i++){
        for(var j=i+1;j<Math.min(i+12,proj.length);j++){
          var dx=proj[i].x-proj[j].x, dy=proj[i].y-proj[j].y;
          var d=Math.hypot(dx,dy);
          if(d<48){
            ctx.strokeStyle='rgba(167,139,250,'+(0.22*(1-d/48))+')';
            ctx.beginPath(); ctx.moveTo(proj[i].x,proj[i].y); ctx.lineTo(proj[j].x,proj[j].y); ctx.stroke();
          }
        }
      }
      for(var i=0;i<proj.length;i++){
        var g=ctx.createRadialGradient(proj[i].x,proj[i].y,0,proj[i].x,proj[i].y,3.2);
        g.addColorStop(0,'rgba(92,225,255,.95)'); g.addColorStop(1,'rgba(92,225,255,0)');
        ctx.fillStyle=g; ctx.beginPath(); ctx.arc(proj[i].x,proj[i].y,3.2,0,Math.PI*2); ctx.fill();
      }
      var red=(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)||document.documentElement.classList.contains('reduce-motion');
      if(!red) requestAnimationFrame(frame);
      else window.addEventListener('ai168:reduce-motion',function(){requestAnimationFrame(frame);},{once:true});
    }
    requestAnimationFrame(frame);
  };
})();
