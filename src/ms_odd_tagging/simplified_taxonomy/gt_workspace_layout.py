from __future__ import annotations


def inject_workspace_layout(html: str) -> str:
    """Constrain the simplified-GT editor to the iframe viewport.

    The original August editor sized the GT card from the BEV element height.
    Inside the newer workspace iframe that could let both the BEV/prediction card
    and GT controls extend below the visible bottom edge. This layout instead
    gives the editor a fixed viewport-height shell and scrolls content inside the
    two cards.
    """
    old = '<section class="card"><div id="form"></div><div class="toolbar">'
    new = (
        '<section class="card" id="taggingCard">'
        '<div id="formScroll"><div id="form"></div></div>'
        '<div class="toolbar">'
    )
    html = html.replace(old, new, 1)

    css = '''<style>
html,body{height:100%;min-height:0;overflow:hidden}
body{display:flex;flex-direction:column}
header{position:relative!important;top:auto!important;flex:0 0 auto}
#timelineWrap{position:relative!important;top:auto!important;flex:0 0 auto}
main{flex:1 1 auto;min-height:0;height:auto!important;overflow:hidden;grid-template-rows:minmax(0,1fr)}
main>.card{height:100%;min-height:0;overflow:hidden}
main>.card:first-child{display:flex;flex-direction:column;min-height:0}
#bev{flex:1 1 auto;min-height:180px;max-height:none!important}
#bev img{width:100%;height:100%;max-height:100%;object-fit:contain}
#bevMissing{min-height:0!important;height:100%}
#bevPath{flex:0 0 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
main>.card:first-child>h3{flex:0 0 auto;margin-top:8px}
#pred{flex:0 0 auto;max-height:18vh;overflow:auto}
#taggingCard{display:flex;flex-direction:column;min-height:0;height:100%!important;max-height:100%!important;overflow:hidden}
#formScroll{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;padding-right:5px}
#taggingCard>.toolbar{flex:0 0 auto;padding-top:8px;border-top:1px solid #374151;background:#1f2937;max-height:92px;overflow-y:auto}
@media(max-width:1000px){
  html,body{height:auto;min-height:100%;overflow:auto}
  body{display:block}
  main{display:grid;height:auto!important;overflow:visible;grid-template-columns:1fr}
  main>.card,#taggingCard{height:auto!important;max-height:none!important;overflow:visible}
  #formScroll{overflow-y:visible}
  #bev{min-height:240px}
  #bev img{height:auto;max-height:none}
}
</style>'''

    # Keep the editor stable when an image loads or the iframe is resized. No
    # element-to-element height syncing is needed: CSS owns the available height.
    script = '''<script>
function __fitWorkspaceEditor(){
  const main=document.querySelector('main');
  if(!main)return;
  if(window.innerWidth<=1000){main.style.minHeight='';return;}
  main.style.minHeight='0';
}
window.addEventListener('resize',__fitWorkspaceEditor);
requestAnimationFrame(__fitWorkspaceEditor);
</script>'''

    html = html.replace('</head>', css + '</head>', 1)
    return html.replace('</body>', script + '</body>', 1)
