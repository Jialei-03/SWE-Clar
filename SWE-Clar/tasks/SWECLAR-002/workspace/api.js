let token='';
export const origin=()=>window.location.origin;
export const getToken=()=>token;
export async function api(path,data){const response=await fetch(origin()+path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:data?JSON.stringify(data):undefined});const value=await response.json();if(!response.ok)throw Error(value.error);if(path==='/login')token=value.token;if(path==='/logout')token='';return value;}
