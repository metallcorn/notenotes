// Ключи разблокированных сейфов живут только в памяти вкладки — намеренно
// НЕ localStorage/sessionStorage: переживают переход по SPA, но не
// перезагрузку страницы или новую вкладку (пользователь явно просил
// "пока браузер не закрыл" — обновил страницу, вводи пароль заново).
import { useEffect, useState } from "react";

const unlockedVaults = new Map<string, CryptoKey>();
const listeners = new Set<() => void>();

function notify(): void {
  // Копия, не живой Set — subscribe/unsubscribe (useEffect ниже) может
  // сработать синхронно как побочный эффект одного из вызовов l() внутри
  // этого же цикла (React планирует ре-рендер, но в React 18 без обёртки
  // в startTransition/событие это иногда всё же исполняется в этом же
  // тике), мутация коллекции во время итерации по ней — undefined behavior.
  for (const l of Array.from(listeners)) l();
}

export function unlockVault(spaceId: string, key: CryptoKey): void {
  unlockedVaults.set(spaceId, key);
  notify();
}

export function lockVault(spaceId: string): void {
  unlockedVaults.delete(spaceId);
  notify();
}

export function getVaultKey(spaceId: string): CryptoKey | undefined {
  return unlockedVaults.get(spaceId);
}

export function isUnlocked(spaceId: string): boolean {
  return unlockedVaults.has(spaceId);
}

// Реальный найденный баг (пойман через ErrorBoundary в проде — "can't
// access property destroy, o is null" внутри минифицированных React-
// внутренностей рядом с useSyncExternalStore): два разных фикса вокруг
// useSyncExternalStore (нестабильный subscribe, затем стабильный
// module-level subscribe) НЕ помогли — краш воспроизводился 1-в-1 на
// каждом деплое. Раз само API стабильно ловит какую-то внутреннюю гонку
// в этой версии React/сборке (4+ одновременных подписчика: useItem/
// useItems/SpaceSection на каждый спейс/AppShell, все просыпаются разом
// на unlockVault/lockVault) — вместо дальнейшего гадания по минифицированному
// коду просто не используем useSyncExternalStore вообще. Обычная подписка
// через useEffect + принудительный ре-рендер — старый, многократно
// проверенный паттерн (то, чем все жили до React 18), без экзотики.
export function useVaultUnlocked(spaceId: string | undefined): boolean {
  const [, forceRerender] = useState(0);
  useEffect(() => {
    const listener = () => forceRerender((n) => n + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return spaceId ? unlockedVaults.has(spaceId) : false;
}
