import { apiFetch } from '../fetcher';
import { SuccessResponse, PaginatedResponse } from '../../types/api.types';
import { User, CreateUserDto, UpdateUserDto } from '../../types/user.dto';

export const userApi = {
  getProfile: () => {
    return apiFetch<User>('/user/me', {
      method: 'GET',
      next: {
        tags: ['user-profile']
      }
    });
  },

  getUsers: (page = 1, limit = 10) => {
    return apiFetch<PaginatedResponse<User>>(`/users?page=${page}&limit=${limit}`, {
      method: 'GET',
      next: {
        revalidate: 60,
        tags: ['users-list']
      }
    });
  },

  createUser: (data: CreateUserDto) => {
    return apiFetch<SuccessResponse<User>>('/users', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store'
    });
  },

  updateUser: (id: string, data: UpdateUserDto) => {
    const endpoint = id === 'me' ? '/user/me' : `/users/${id}`;
    return apiFetch<User>(endpoint, {
      method: 'PATCH',
      body: JSON.stringify(data),
      cache: 'no-store'
    });
  },
  
  deleteUser: (id: string) => {
    return apiFetch<SuccessResponse<null>>(`/users/${id}`, {
      method: 'DELETE',
      cache: 'no-store'
    });
  }
};
