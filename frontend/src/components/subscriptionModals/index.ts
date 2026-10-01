export { default as CommonContent, type CommonModalProps } from './CommonContent';
export { default as Pricing, type PricingProps } from './Pricing';
export { default as BuyToken, type BuyTokenProps, type TokenBundle } from './BuyToken';
export { default as NoFreeToken, type NoFreeTokenProps } from './NoFreeToken';
export { default as OutOfFreeToken, type OutOfFreeTokenProps } from './OutOfFreeToken';
export { default as OutOfToken, type OutOfTokenProps } from './OutOfToken';
export { default as RunningOutToken, type RunningOutTokenProps } from './RunningOutToken';

export const SUBSCRIPTION_MODAL_OVERLAY_PROPS = {
  backgroundOpacity: 0.11,
  blur: 40,
  style: {
    background: 'rgba(9, 9, 9, 0.11)',
    backdropFilter: 'blur(40px)',
    WebkitBackdropFilter: 'blur(40px)',
  },
};

export const SUBSCRIPTION_MODAL_STYLES = {
  overlay: {
    background: 'rgba(9, 9, 9, 0.11)',
    backdropFilter: 'blur(40px)',
    WebkitBackdropFilter: 'blur(40px)',
  },
  content: { background: 'transparent', boxShadow: 'none' },
  body: { padding: 0 },
};
