import EmojiPicker, { type EmojiClickData } from "emoji-picker-react";

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
          searchPlaceHolder="Поиск эмодзи"
        />
      </div>
    </div>
  );
}
