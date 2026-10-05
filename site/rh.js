/* RepoHunter shared behaviour: copy buttons, the install picker, and the nav "check a repo" box. */
(function(){
  var GIT='git+https://github.com/meetziggy/repohunter@v0.2.1';

  // Install picker: one-liner per AI client, one-click links where the client supports them.
  Array.prototype.forEach.call(document.querySelectorAll('[data-picker]'),function(box){
    var sel=box.querySelector('select'), pre=box.querySelector('pre'),
        row=box.querySelector('.openrow'), link=box.querySelector('.openrow a'),
        next=box.querySelector('[data-next]');
    var args=['--from',GIT,'repohunter-mcp'], server={command:'uvx',args:args};
    var json='{\n  "mcpServers": {\n    "repohunter": {\n      "command": "uvx",\n      "args": ["--from", "'+GIT+'", "repohunter-mcp"]\n    }\n  }\n}';
    var agentNext='Your agent can now check what exists before it builds or installs.';
    var C={
      claude:{cmd:'claude mcp add repohunter -- uvx --from '+GIT+' repohunter-mcp',next:agentNext},
      codex:{cmd:'codex mcp add repohunter -- uvx --from '+GIT+' repohunter-mcp',next:agentNext},
      cursor:{cmd:json,open:'Open in Cursor',next:agentNext,
        href:'cursor://anysphere.cursor-deeplink/mcp/install?name=repohunter&config='+encodeURIComponent(btoa(JSON.stringify(server)))},
      vscode:{cmd:json,open:'Open in VS Code',next:agentNext,
        href:'vscode:mcp/install?'+encodeURIComponent(JSON.stringify({name:'repohunter',command:'uvx',args:args}))},
      json:{cmd:json,next:'Paste into your client\'s MCP config, then restart it.'},
      cli:{cmd:'uvx --from '+GIT+' repohunter scan rtk-ai/rtk',next:'Runs once with no install. Swap in any owner/repo.'}
    };
    function show(k){
      var c=C[k]||C.claude; pre.textContent=c.cmd;
      if(c.href){ link.href=c.href; link.textContent=c.open; row.hidden=false; } else row.hidden=true;
      if(next) next.textContent=c.next;
      try{ localStorage.setItem('rh-client',k); }catch(e){}
    }
    sel.addEventListener('change',function(){ show(sel.value); });
    var saved=null; try{ saved=localStorage.getItem('rh-client'); }catch(e){}
    if(saved&&C[saved]) sel.value=saved;
    show(sel.value);
  });

  // Every .codeblock gets a working copy button; [data-copy] buttons copy the element they name.
  function wire(btn,getText){
    btn.addEventListener('click',function(){
      if(!navigator.clipboard) return;
      var label=btn.textContent;
      navigator.clipboard.writeText(getText()).then(function(){
        btn.textContent='Copied'; btn.classList.add('done');
        var live=document.getElementById('rh-live'); if(live) live.textContent='Copied to clipboard';
        setTimeout(function(){ btn.textContent=label; btn.classList.remove('done'); },1500);
      });
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll('[data-copy]'),function(b){
    wire(b,function(){ return (document.getElementById(b.getAttribute('data-copy'))||{}).textContent||''; });
  });
  Array.prototype.forEach.call(document.querySelectorAll('.codeblock'),function(cb){
    var b=cb.querySelector('.cb-bar .copy'), pre=cb.querySelector('pre');
    if(b&&pre&&!b.hasAttribute('data-copy')) wire(b,function(){ return pre.textContent; });
  });

  // Nav box on sub-pages: route to the home page's check panel.
  var nf=document.getElementById('navcheck');
  if(nf) nf.addEventListener('submit',function(e){
    e.preventDefault(); var v=(nf.querySelector('input').value||'').trim();
    if(v) location.href='/?q='+encodeURIComponent(v)+'#check';
  });
})();
