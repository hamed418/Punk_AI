import { userApi } from '../lib/api/user';
import { CreateUserDto, CreateUserDtoSchema, UpdateUserDto, UpdateUserDtoSchema } from '../types/user.dto';
import { revalidateTag } from 'next/cache';

export class UserService {
  static async getCurrentProfile() {
    try {
      const response = await userApi.getProfile();
      return response;
    } catch (error) {
      console.error('Failed to get current profile:', error);
      throw error;
    }
  }

  static async listUsers(page: number = 1, limit: number = 10) {
    try {
      const response = await userApi.getUsers(page, limit);
      return response;
    } catch (error) {
      console.error('Failed to list users:', error);
      throw error;
    }
  }

  static async createUser(data: CreateUserDto) {
    try {
      const validatedData = CreateUserDtoSchema.parse(data);
      const response = await userApi.createUser(validatedData);
      
      // @ts-expect-error: Next.js revalidateTag
      revalidateTag('users-list');
      
      return response.data;
    } catch (error) {
      console.error('Failed to create user:', error);
      throw error;
    }
  }

  static async updateUser(id: string, data: UpdateUserDto) {
    try {
      const validatedData = UpdateUserDtoSchema.parse(data);
      const response = await userApi.updateUser(id, validatedData);
      
      // @ts-expect-error: Next.js revalidateTag
      revalidateTag('user-profile');
      // @ts-expect-error: Next.js revalidateTag
      revalidateTag('users-list');
      
      return response;
    } catch (error) {
      console.error('Failed to update user:', error);
      throw error;
    }
  }

  static async deleteUser(id: string) {
    try {
      await userApi.deleteUser(id);
      // @ts-expect-error: Next.js revalidateTag
      revalidateTag('users-list');
      return { success: true };
    } catch (error) {
      console.error('Failed to delete user:', error);
      throw error;
    }
  }
}
