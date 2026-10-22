export function transition(state,event,config) {
  const next=structuredClone(state);
  if(event.type==='navigate') {
    if(!config.routes.includes(event.route))return {...next,error:'unknown_route'};
    if(config.protectedRoutes.includes(event.route)&&!config.authenticated)return {...next,error:'auth_required'};
    next.route=event.route;next.error='';
  } else if(event.type==='toggle_filter')next.openNow=next.openNow;
  return next;
}
export const displayRating=value=>String(value);
