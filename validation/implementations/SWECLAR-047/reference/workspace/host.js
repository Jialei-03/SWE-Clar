export async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error);
  return value;
}
export function element(tag, text, attributes = {}) {
  const node = document.createElement(tag); if (text !== undefined) node.textContent = text;
  for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,value);
  return node;
}
export function message(error) { document.querySelector('#message').textContent = error ? error.message : ''; }
export class NotebookHost {
  constructor() { this.nodes = []; this.current = null; this.pendingEdits = new Set(); }
  async flush() {
    // A sidebar click can blur an editor and start its save immediately before
    // the sidebar command.  Await those saves so a new default bookmark label
    // and every subsequent domain mutation observe the edited document.
    await Promise.all([...this.pendingEdits]);
  }
  async refresh() {
    const data = await request('/api/document'); this.nodes = data.nodes; this.current = data.current; this.render();
  }
  ancestors(id = this.current) {
    const result = [];
    while (id) { const node = this.nodes.find(x=>x.id===id); if (!node) break; result.unshift(node); id = node.parent; }
    return result;
  }
  async navigate(id) { await this.flush(); await request('/api/host',{type:'navigate',id}); await this.refresh(); }
  target(kind) { return this.ancestors().find(x=>x.kind===kind); }
  render() {
    const nav = document.querySelector('#document-nav'); nav.replaceChildren();
    for (const node of this.nodes.filter(x=>x.kind!=='paragraph')) {
      const button = element('button',node.text,{'data-object':node.id});
      button.style.paddingLeft = `${10+this.ancestors(node.id).length*10}px`;
      button.onclick = ()=>this.navigate(node.id).catch(message); nav.append(button);
    }
    const current = this.nodes.find(x=>x.id===this.current);
    document.querySelector('#document-title').textContent = current.text;
    document.querySelector('#breadcrumbs').textContent = this.ancestors().map(x=>x.text).join(' / ');
    const editor = document.querySelector('#editor'); editor.replaceChildren();
    const page = current.kind==='paragraph' ? current.parent : current.id;
    for (const node of this.nodes.filter(x=>x.kind==='paragraph' && x.parent===page)) {
      const row = element('p',node.text,{contenteditable:'true','data-paragraph':node.id,tabindex:'0'});
      row.addEventListener('focus',()=>{this.current=node.id;request('/api/host',{type:'navigate',id:node.id}).catch(message);});
      row.addEventListener('blur',()=>{
        const pending = request('/api/host',{type:'edit',id:node.id,text:row.textContent})
          .then(()=>{node.text=row.textContent;})
          .catch(message);
        this.pendingEdits.add(pending);
        pending.then(()=>this.pendingEdits.delete(pending),()=>this.pendingEdits.delete(pending));
      });
      editor.append(row);
    }
    if (current.kind==='paragraph') {
      const row=editor.querySelector(`[data-paragraph="${current.id}"]`); row?.focus(); row?.scrollIntoView({block:'nearest'});
    }
  }
}
