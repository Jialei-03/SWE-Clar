(() => {
  const byId = (id) => document.getElementById(id);
  const data = window.FLEET_DATA;
  const fillList = (element, rows) => {
    element.replaceChildren();
    rows.forEach((row) => {
      const item = document.createElement('li');
      item.className = 'list-group-item';
      item.textContent = row.name;
      item.dataset.recordId = row.id;
      element.append(item);
    });
  };
  const showError = (error) => {
    byId('error').hidden = false;
    byId('error').textContent = error.code + ': ' + (error.fields || []).join(', ');
    return {error};
  };
  const render = () => {
    const missing = ['summary','drivers','vehicles'].filter((key) => !Object.hasOwn(data,key));
    if (missing.length) return showError({code:'missing_data',fields:missing});
    byId('error').hidden = true;
    byId('summary').replaceChildren();
    Object.entries(data.summary).forEach(([label,value]) => {
      const tile=document.createElement('div'); tile.className='summary-tile';
      const heading=document.createElement('span');heading.textContent=label;
      const number=document.createElement('div');number.className='summary-value';number.textContent=String(value);
      tile.append(heading,number);byId('summary').append(tile);
    });
    fillList(byId('drivers'),data.drivers);fillList(byId('vehicles'),data.vehicles);
    return {ok:true};
  };
  const dispatch = (action) => ({ok:true});
  window.dashboard = {dispatch, render};
  byId('view-drivers').addEventListener('click',()=>dispatch({type:'view_all',target:'drivers'}));
  byId('view-vehicles').addEventListener('click',()=>dispatch({type:'view_all',target:'vehicles'}));
  byId('close-sidebar').addEventListener('click',()=>dispatch({type:'close_sidebar'}));
  render();
})();
