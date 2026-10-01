import { notifications } from '@mantine/notifications';

export const showSuccessNotification = (title: string, message?: string) => {
  notifications.show({
    title,
    message: message || '',
    color: 'green',
    autoClose: 4000,
    withCloseButton: true,
  });
};

export const showErrorNotification = (title: string, message?: string) => {
  notifications.show({
    title,
    message: message || '',
    color: 'red',
    autoClose: 5000,
    withCloseButton: true,
  });
};

export const showInfoNotification = (title: string, message?: string) => {
  notifications.show({
    title,
    message: message || '',
    color: 'blue',
    autoClose: 4000,
    withCloseButton: true,
  });
};
