/* Scribe: optional, deterministic, no new model calls or financial writes. */
(function(){
'use strict';
if(window.DuoCompanion)return;
var KEY='duospend_companion',pref=false,locked=true,editing=false,context={},activeTab='home',busy=0,turn=0,timers=[];
var mq=window.matchMedia?window.matchMedia('(prefers-reduced-motion: reduce)'):{matches:true};
var images=['idle','step-a','step-b','greeting'].map(function(s){return '/assets/scribe/'+s+'.webp';});
try{pref=localStorage.getItem(KEY)==='1';}catch(e){}
var dock=document.createElement('aside');dock.id='scribeDock';dock.hidden=true;dock.setAttribute('aria-label','Scribe, compagnon facultatif');
dock.innerHTML='<button type="button" class="scribe-stage" aria-label="Voir le conseil de Scribe"><img src="'+images[0]+'" width="62" height="78" alt="Scribe, petit renard illustré avec son carnet" decoding="async"></button><div class="scribe-copy"><span class="scribe-eyebrow">Scribe · repères calculés</span><span class="scribe-status" role="status" aria-live="polite"></span><button type="button" class="scribe-action"></button></div><button type="button" class="scribe-close" aria-label="Désactiver Scribe">×</button>';
document.body.appendChild(dock);
var toolbar=document.createElement('div');toolbar.className='scribe-toolbar';toolbar.hidden=true;
toolbar.innerHTML='<span>Compagnon facultatif</span><button type="button" class="scribe-toggle" aria-pressed="false">Activer Scribe</button>';
var head=document.querySelector('.head')||document.querySelector('.header');
if(head)head.insertAdjacentElement('afterend',toolbar);else document.body.appendChild(toolbar);
var lane=document.querySelector('.month-bar')||toolbar;
lane.insertAdjacentElement('afterend',dock);
var img=dock.querySelector('img'),status=dock.querySelector('.scribe-status'),action=dock.querySelector('.scribe-action'),toggle=toolbar.querySelector('button');
var targetTab='assistant';
function count(x){var n=Number(x);return Number.isFinite(n)?Math.max(0,Math.floor(n)):0;}
function plural(n,one,many){return n+' '+(n===1?one:many);}
function clearMotion(){timers.forEach(clearTimeout);timers=[];dock.dataset.pose='idle';img.src=images[0];}
function paint(){
 toolbar.hidden=locked;toggle.setAttribute('aria-pressed',String(pref));toggle.textContent=pref?'Désactiver Scribe':'Activer Scribe';
 var show=pref&&!locked;
 dock.hidden=!show;document.body.classList.toggle('has-scribe',show);
 if(!show)clearMotion();
}
function advice(){
 if(busy){status.textContent='Analyse en cours. Aucune dépense ajoutée automatiquement.';action.hidden=true;return;}
 action.hidden=false;
 var u=count(context.uncategorized),o=count(context.overBudget),s=count(context.shoppingRemaining);
 if(u){status.textContent=plural(u,'opération attend son classement.','opérations attendent leur classement.');action.textContent='Ouvrir le registre';targetTab='registry';}
 else if(o){status.textContent=plural(o,'enveloppe dépasse le repère fixé.','enveloppes dépassent les repères fixés.');action.textContent='Voir les enveloppes';targetTab='envelopes';}
 else if(activeTab==='shopping'&&s){status.textContent=plural(s,'article reste à cocher.','articles restent à cocher.');action.textContent='Préparer le repas';targetTab='decider';}
 else if(activeTab==='decider'){status.textContent='Des idées pour ce soir, pas une obligation de dépenser.';action.textContent='Voir la liste de courses';targetTab='shopping';}
 else if(activeTab==='assistant'){status.textContent='Les chiffres viennent du registre. Les suggestions restent à confirmer.';action.textContent='Vérifier le registre';targetTab='registry';}
 else{status.textContent='Un doute sur une avance ou un classement ? Je vous guide vers le bon carnet.';action.textContent='Ouvrir l’assistant';targetTab='assistant';}
}
function gesture(pose){
 clearMotion();if(dock.hidden||mq.matches||document.hidden||editing)return;
 var box=dock.getBoundingClientRect();if(box.bottom<=0||box.top>=window.innerHeight)return;
 var token=++turn;
 if(pose==='greeting'){dock.dataset.pose='greeting';img.src=images[3];timers.push(setTimeout(clearMotion,1600));return;}
 dock.dataset.pose='walk';
 [0,160,320,480,640].forEach(function(delay,i){timers.push(setTimeout(function(){if(token===turn&&!dock.hidden)img.src=images[i%2+1];},delay));});
 timers.push(setTimeout(clearMotion,960));
}
function enable(){pref=true;try{localStorage.setItem(KEY,'1');}catch(e){}advice();paint();gesture('greeting');}
function disable(){pref=false;try{localStorage.setItem(KEY,'0');}catch(e){}paint();}
function setState(detail){context=detail||{};locked=!context.user;advice();paint();}
function setLocked(value){locked=!!value;if(locked){context={};busy=0;turn++;}advice();paint();}
function navigate(tab){
 var map={registry:'tab-overview',import:'tab-overview',envelopes:'tab-envelopes',shopping:'tab-shopping',assistant:'tab-assistant',decider:'tab-quests'};
 var button=document.querySelector('.tab-btn[data-tab="'+map[tab]+'"]');
 if(button){button.click();if(tab==='registry'||tab==='import'){var el=document.querySelector(tab==='registry'?'#txList':'#importCard');if(el)el.scrollIntoView({behavior:mq.matches?'auto':'smooth',block:'start'});}return;}
 window.location.assign('/app.html?tab='+encodeURIComponent(tab));
}
toggle.addEventListener('click',function(){pref?disable():enable();});
dock.querySelector('.scribe-close').addEventListener('click',disable);
dock.querySelector('.scribe-stage').addEventListener('click',function(){advice();gesture('greeting');});
action.addEventListener('click',function(){navigate(targetTab);});
document.addEventListener('duospend:state',function(e){setState(e.detail);});
document.addEventListener('duospend:locked',function(){setLocked(true);});
document.addEventListener('duospend:tab',function(e){activeTab=(e.detail||{}).tab||'home';advice();gesture('walk');});
document.addEventListener('visibilitychange',function(){paint();});
document.addEventListener('focusin',function(e){editing=!!e.target.closest('input:not([type=checkbox]):not([type=radio]),textarea,select');paint();});
document.addEventListener('focusout',function(){timers.push(setTimeout(function(){editing=!!(document.activeElement&&document.activeElement.closest('input:not([type=checkbox]):not([type=radio]),textarea,select'));paint();},90));});
window.addEventListener('storage',function(e){if(e.key===KEY){pref=e.newValue==='1';paint();}else if(e.key==='duospend_code'&&!e.newValue){setLocked(true);}});
if(mq.addEventListener)mq.addEventListener('change',clearMotion);
// Existing auth wrapper keeps control. Inspect status only, leave bodies untouched.
var fetchBefore=window.fetch;
if(typeof fetchBefore==='function')window.fetch=function(input,options){
 var url=String(input&&input.url||input),method=String(options&&options.method||input&&input.method||'GET').toUpperCase();
 var tracked=method==='POST'&&/\/api\/(assistant$|import\/analyze|classify|meals|shopping\/analyze)/.test(url);
 if(!tracked)return fetchBefore.apply(this,arguments);
 busy++;advice();var args=arguments,self=this;
 return Promise.resolve().then(function(){return fetchBefore.apply(self,args);}).then(function(r){busy=Math.max(0,busy-1);advice();if(r.ok)gesture('greeting');return r;},function(error){busy=Math.max(0,busy-1);advice();throw error;});
};
window.DuoCompanion=Object.freeze({enable:enable,disable:disable,setState:setState,setLocked:setLocked,navigate:navigate,react:gesture});
if(window.DuoHome&&window.DuoHome.context)setState(window.DuoHome.context());
else if(window.DuoApp&&window.DuoApp.context){setState(window.DuoApp.context());if(window.DuoApp.tab)activeTab=window.DuoApp.tab()||'registry';advice();}
paint();
})();
