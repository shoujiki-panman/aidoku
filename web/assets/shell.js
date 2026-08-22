// 上のメニューの開け閉め。全ページ共通。
//
// <details> は素のままだと「外を押しても閉じない」。押した本人は
// 閉じたつもりで次を押すので、メニューが画面に残って邪魔になる。
// 外を押す・Escape・項目を選ぶ、のどれでも閉じるようにする。
(function () {
  'use strict';
  const menu = document.querySelector('.menu');
  if (!menu) return;

  const close = () => { menu.open = false; };

  // 外側を押したら閉じる。中を押したときは閉じない
  document.addEventListener('click', (e) => {
    if (menu.open && !menu.contains(e.target)) close();
  });
  // 項目を選んだら閉じる（同じページ内のアンカーだと遷移せず残る）
  menu.addEventListener('click', (e) => {
    if (e.target.closest('a')) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !menu.open) return;
    close();
    const summary = menu.querySelector('summary');
    if (summary) summary.focus();   // 閉じたあと、開くボタンに戻す
  });
})();
