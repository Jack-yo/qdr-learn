/* QDR global chart/market direction colors.
 * Default for US stocks: green = rise, red = fall.
 * One accessible switch supports red-rise / green-fall conventions.
 * Saved preference changes ONLY presentation; numeric values stay unchanged.
 */
(() => {
 'use strict';
 const root=document.documentElement;
 const button=document.getElementById('v4-color-mode');
 if(!root || !button)return;
 const KEY='qdr.market.direction.palette.v1';
 let saved='';
 try{saved=window.localStorage?.getItem(KEY)||''}catch(_){}
 function use(mode) {
   const palette=mode==='red-up'?'red-up':'green-up';
   root.setAttribute('data-change-palette',palette);
   button.textContent=palette==='red-up'?'红涨绿跌':'绿涨红跌';
   button.setAttribute('aria-label','切换涨跌配色，当前'+button.textContent);
   button.setAttribute('title','点击切换红绿涨跌颜色，仅改变显示，不影响预测与数据');
   button.setAttribute('aria-pressed',String(palette==='red-up'));
   return palette;
 }
 let current=use(saved);
 button.addEventListener('click',()=>{
   current=use(current==='red-up'?'green-up':'red-up');
   try{window.localStorage?.setItem(KEY,current)}catch(_){}
 });
})();
