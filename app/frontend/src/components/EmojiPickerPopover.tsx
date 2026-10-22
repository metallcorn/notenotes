import EmojiPicker, { Theme, type EmojiClickData } from "emoji-picker-react";

export default function EmojiPickerPopover({
  onSelect,
  onClose,
}: {
  onSelect: (emoji: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute z-20 mt-1">
      <div className="fixed inset-0" onClick={onClose} />
      <div className="relative">
        <EmojiPicker
          onEmojiClick={(data: EmojiClickData) => {
            onSelect(data.emoji);
            onClose();
          }}
          width={320}
          height={400}
          // Тема пикера — по классу .dark на <html> (lib/theme.ts): иначе в
          // тёмной теме всплывает белая панель.
          theme={document.documentElement.classList.contains("dark") ? Theme.DARK : Theme.LIGHT}
          searchPlaceHolder="Поиск эмодзи"
        />
      </div>
    </div>
  );
}
