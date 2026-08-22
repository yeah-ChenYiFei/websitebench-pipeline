export function createPromoState({ itemCount, visibleCount, onChange }) {
  if (!Number.isInteger(itemCount) || itemCount < 1) {
    throw new TypeError('itemCount must be a positive integer');
  }
  if (!Number.isInteger(visibleCount) || visibleCount < 1 || visibleCount > itemCount) {
    throw new TypeError('visibleCount must be between 1 and itemCount');
  }
  if (typeof onChange !== 'function') {
    throw new TypeError('onChange must be a function');
  }

  let index = 0;

  const normalize = (value) => ((value % itemCount) + itemCount) % itemCount;
  const snapshot = () => ({
    index,
    visibleIndexes: Array.from(
      { length: visibleCount },
      (_, offset) => normalize(index + offset),
    ),
  });
  const publish = () => onChange(snapshot());

  const state = {
    next() {
      index = normalize(index + 1);
      publish();
    },
    previous() {
      index = normalize(index - 1);
      publish();
    },
    goTo(nextIndex) {
      if (!Number.isInteger(nextIndex)) {
        throw new TypeError('index must be an integer');
      }
      index = normalize(nextIndex);
      publish();
    },
    getIndex() {
      return index;
    },
  };

  publish();
  return state;
}
