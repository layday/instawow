export const makeDuplicativeState = <T>(initialValue: T) => {
  let internalState = $state<{
    initial: T;
    current: T;
  }>({
    initial: initialValue,
    current: initialValue,
  });

  return {
    get initial() {
      return internalState.initial;
    },
    get current() {
      return internalState.current;
    },
    reset(value: T) {
      internalState = {
        initial: structuredClone(value),
        current: structuredClone(value),
      };
    },
  };
};
