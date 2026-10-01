'use client';

import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import { Box, Loader } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { ArrowRight, X, Check } from 'lucide-react';
import React, { useRef, useState, useMemo } from 'react';
import { useGetFaqCategories } from '../../../../hooks/api/useFaqApi';
import { useCreateSupportTicket } from '../../../../hooks/api/useSupportApi';
import { FAQCategory } from '../../../../types/faq.types';
import { trackEvent } from '@/lib/analytics';
import { z } from 'zod';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

const supportTicketSchema = z.object({
    name: z
        .string()
        .min(1, 'Name is required')
        .min(2, 'Name must be at least 2 characters'),
    email: z
        .string()
        .min(1, 'Email is required')
        .email('Please enter a valid email address'),
    description: z
        .string()
        .min(1, 'Description is required')
        .min(10, 'Description must be at least 10 characters'),
    attachments: z
        .array(z.custom<File>())
        .refine(
            (files) => files.every((file) => !file || file.size <= MAX_FILE_SIZE),
            'Each file must not exceed 10MB'
        )
        .optional(),
});

export default function SupportCard() {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [selectedCategoryName, setSelectedCategoryName] = useState<string>('');
    const [description, setDescription] = useState('');
    const [attachments, setAttachments] = useState<File[]>([]);
    const [errors, setErrors] = useState<{ [key: string]: string | undefined }>({});
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Fetch categories and filter for support
    const { data: categoriesData, isLoading: categoriesLoading } = useGetFaqCategories();
    const CATEGORIES = useMemo(() => {
        if (!categoriesData) return [];
        return categoriesData.filter((c: FAQCategory) => c.type === 'support' || c.type === 'both');
    }, [categoriesData]);

    // Setup Create Mutation
    const createTicketMutation = useCreateSupportTicket();

    const activeCategoryName = selectedCategoryName || (CATEGORIES.length > 0 ? CATEGORIES[0].name : '');

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            const filesArray = Array.from(e.target.files);
            const oversizedFile = filesArray.find((file) => file.size > MAX_FILE_SIZE);
            if (oversizedFile) {
                setErrors((prev) => ({
                    ...prev,
                    attachments: `File "${oversizedFile.name}" exceeds the 10MB limit. Maximum allowed size is 10MB.`,
                }));
                if (fileInputRef.current) fileInputRef.current.value = '';
                return;
            }

            setErrors((prev) => ({ ...prev, attachments: undefined }));
            setAttachments((prev) => [...prev, ...filesArray]);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const removeAttachment = (indexToRemove: number) => {
        setAttachments((prev) => {
            const next = prev.filter((_, idx) => idx !== indexToRemove);
            if (next.every((file) => file.size <= MAX_FILE_SIZE)) {
                setErrors((prevErr) => ({ ...prevErr, attachments: undefined }));
            }
            return next;
        });
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        // Validate using Zod schema
        const validation = supportTicketSchema.safeParse({
            name: name.trim(),
            email: email.trim(),
            description: description.trim(),
            attachments,
        });

        if (!validation.success) {
            const fieldErrors: { [key: string]: string } = {};
            for (const issue of validation.error.issues) {
                const field = issue.path[0] as string;
                if (field && !fieldErrors[field]) {
                    fieldErrors[field] = issue.message;
                }
            }
            setErrors(fieldErrors);
            return;
        }

        setErrors({});

        const selectedCat = CATEGORIES.find(c => c.name === activeCategoryName);

        const formData = new FormData();
        formData.append('name', name.trim());
        formData.append('email', email.trim());
        formData.append('description', description.trim());
        if (selectedCat) {
            formData.append('category_id', selectedCat.id);
        }

        // Only attaching the first file for now, since backend endpoint accepts Optional[UploadFile] 
        // as opposed to List[UploadFile]
        if (attachments.length > 0) {
            formData.append('attachment', attachments[0]);
        }

        try {
            await createTicketMutation.mutateAsync(formData);

            trackEvent('Feedback Submitted', {
                name: name.trim(),
                email: email.trim(),
                category: activeCategoryName,
                description: description.trim(),
                has_attachment: attachments.length > 0,
            });
            trackEvent('feedback_submitted', {
                name: name.trim(),
                email: email.trim(),
                category: activeCategoryName,
                description: description.trim(),
                has_attachment: attachments.length > 0,
            });

            notifications.show({
                title: 'Success',
                message: 'Thank you! Your ticket has been submitted to Punk AI Support.',
                color: 'green',
                icon: <Check className="size-4" />,
            });
            // Reset form
            setName('');
            setEmail('');
            setDescription('');
            setAttachments([]);
            setErrors({});
            if (CATEGORIES.length > 0) setSelectedCategoryName(CATEGORIES[0].name);
        } catch (error) {
            console.error('Failed to submit ticket', error);
            notifications.show({
                title: 'Error',
                message: 'Failed to submit ticket. Please try again.',
                color: 'red',
                icon: <X className="size-4" />,
            });
        }
    };

    return (
        <Box className="mx-auto max-w-375 px-4 py-12 md:px-8 md:py-16">
            <div
                className="relative overflow-hidden rounded-3xl border border-[#FFFFFF14] p-6 md:p-10 lg:p-12"
                style={{
                    backgroundColor: '#FFFFFF03',
                    boxShadow:
                        '0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',
                    backdropFilter: 'blur(75.9px)',
                }}
            >
                <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 lg:gap-12">
                    {/* Left Column */}
                    <div className="flex flex-col justify-between lg:col-span-4 lg:border-r lg:border-[#FFFFFF12] lg:pr-8 2xl:pr-40">
                        <div>
                            <span className="text-[11px] font-bold tracking-[1.8px]! leading-[16.5px]! text-primary-text/35! uppercase">
                                STILL STUCK?
                            </span>

                            <h2 className="mt-5 text-2xl! font-bold leading-[32.5px]! text-primary-text sm:text-[28px]!">
                                Email Punk AI Support
                            </h2>

                            <p className="mt-3 text-[13px]! font-normal leading-5.25! text-primary-text/45">
                                Describe what happened and attach a screenshot if you have one. We read every message.
                            </p>

                            {/* Direct Info List */}
                            <div className="space-y-6 pt-8">
                                <div className="flex items-start space-x-3">
                                    <ArrowRight className="mt-1.5 size-4 shrink-0 text-[#F54397]" />
                                    <div>
                                        <a
                                            href="mailto:support@punkai.com"
                                            className="text-[13px] font-semibold leading-[19.5px]! text-primary-text transition-colors hover:text-pink-400"
                                        >
                                            support@punkai.com
                                        </a>
                                        <p className="text-xs leading-4.5 text-primary-text/38 font-normal">Or write to us directly</p>
                                    </div>
                                </div>

                                <div className="flex items-start space-x-3">
                                    <ArrowRight className="mt-1.5 size-4 shrink-0 text-[#F54397]" />
                                    <div>
                                        <span className="text-[13px] font-semibold leading-[19.5px]! text-primary-text">Within 24 hours</span>
                                        <p className="text-xs leading-4.5 text-primary-text/38 font-normal">Mon–Fri, faster for Pro subscribers</p>
                                    </div>
                                </div>

                                <div className="flex items-start space-x-3">
                                    <ArrowRight className="mt-1.5 size-4 shrink-0 text-[#F54397]" />
                                    <div>
                                        <span className="text-[13px] font-semibold leading-[19.5px]! text-primary-text">A person, not a bot</span>
                                        <p className="text-xs leading-4.5 text-primary-text/38 font-normal">No automated replies</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Right Column: Support Form */}
                    <div className="lg:col-span-8">
                        <form onSubmit={handleSubmit} noValidate className="space-y-6">
                            {/* Name and Email Inputs */}
                            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                                <div className="space-y-2">
                                    <label htmlFor="support-name" className="text-[13px]! font-bold leading-[19.5px]! text-primary-text/80">
                                        Your name
                                    </label>
                                    <input
                                        id="support-name"
                                        type="text"
                                        value={name}
                                        onChange={(e) => {
                                            setName(e.target.value);
                                            if (errors.name) {
                                                setErrors((prev) => ({ ...prev, name: undefined }));
                                            }
                                        }}
                                        placeholder="Alex Rahman"
                                        className={`w-full rounded-full border! bg-[#FFFFFF05]! px-5 py-3 text-sm text-white placeholder:text-neutral-500 backdrop-blur-[58.1px] transition-all focus:outline-none ${
                                            errors.name
                                                ? 'border-red-500/60! focus:border-red-400!'
                                                : 'border-[#FFFFFF1C]! focus:border-white/30!'
                                        }`}
                                        style={{
                                            backgroundColor: '#FFFFFF05',
                                            border: errors.name
                                                ? '1px solid rgba(239, 68, 68, 0.6)'
                                                : '1px solid rgba(255, 255, 255, 0.12)',
                                            backdropFilter: 'blur(58.1px)',
                                            WebkitBackdropFilter: 'blur(58.1px)',
                                        }}
                                    />
                                    {errors.name && (
                                        <p className="px-1 text-xs text-red-400 leading-tight">
                                            {errors.name}
                                        </p>
                                    )}
                                </div>

                                <div className="space-y-2">
                                    <label htmlFor="support-email" className="text-[13px]! font-bold leading-[19.5px]! text-primary-text/80">
                                        Email
                                    </label>
                                    <input
                                        id="support-email"
                                        type="email"
                                        value={email}
                                        onChange={(e) => {
                                            setEmail(e.target.value);
                                            if (errors.email) {
                                                setErrors((prev) => ({ ...prev, email: undefined }));
                                            }
                                        }}
                                        placeholder="you@company.com"
                                        className={`w-full rounded-full border! bg-[#FFFFFF05]! px-5 py-3 text-sm text-white placeholder:text-neutral-500 backdrop-blur-[58.1px] transition-all focus:outline-none ${
                                            errors.email
                                                ? 'border-red-500/60! focus:border-red-400!'
                                                : 'border-[#FFFFFF1C]! focus:border-white/30!'
                                        }`}
                                        style={{
                                            backgroundColor: '#FFFFFF05',
                                            border: errors.email
                                                ? '1px solid rgba(239, 68, 68, 0.6)'
                                                : '1px solid rgba(255, 255, 255, 0.12)',
                                            backdropFilter: 'blur(58.1px)',
                                            WebkitBackdropFilter: 'blur(58.1px)',
                                        }}
                                    />
                                    {errors.email && (
                                        <p className="px-1 text-xs text-red-400 leading-tight">
                                            {errors.email}
                                        </p>
                                    )}
                                </div>
                            </div>

                            {/* What's this about? Category Selector */}
                            <div className="space-y-2">
                                <label className="text-xs font-medium text-neutral-300">What&apos;s this about?</label>
                                <div className="flex flex-wrap gap-2 pt-1">
                                    {categoriesLoading ? (
                                        <Loader color="gray" size="sm" />
                                    ) : CATEGORIES.map((cat) => {
                                        const isSelected = activeCategoryName === cat.name;
                                        return (
                                            <button
                                                key={cat.id}
                                                type="button"
                                                onClick={() => setSelectedCategoryName(cat.name)}
                                                className={`cursor-pointer rounded-full px-3 py-1 text-[11px] font-medium transition-all ${isSelected
                                                    ? 'border border-neutral-500 bg-neutral-800 text-white shadow-sm'
                                                    : 'border border-[#FFFFFF12] bg-[#161619]/60 text-neutral-400 hover:border-neutral-700 hover:text-neutral-200'
                                                    }`}
                                            >
                                                {cat.name}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Problem Description */}
                            <div className="space-y-2">
                                <label htmlFor="support-desc" className="text-[13px]! font-bold leading-[19.5px]! text-primary-text/80">
                                    Describe the problem
                                </label>
                                <textarea
                                    id="support-desc"
                                    rows={4}
                                    value={description}
                                    onChange={(e) => {
                                        setDescription(e.target.value);
                                        if (errors.description) {
                                            setErrors((prev) => ({ ...prev, description: undefined }));
                                        }
                                    }}
                                    placeholder="Tell us what happened, and what you expected to happen instead."
                                    className={`w-full resize-none mt-2 rounded-2xl border! bg-[#FFFFFF05]! px-5 py-3.5 text-[13px]! leading-4.75! text-primary placeholder:text-[#6F7173] backdrop-blur-[58.1px] transition-all focus:outline-none ${
                                        errors.description
                                            ? 'border-red-500/60! focus:border-red-400!'
                                            : 'border-[#FFFFFF1C]! focus:border-white/30!'
                                    }`}
                                    style={{
                                        backgroundColor: '#FFFFFF05',
                                        border: errors.description
                                            ? '1px solid rgba(239, 68, 68, 0.6)'
                                            : '1px solid rgba(255, 255, 255, 0.12)',
                                        backdropFilter: 'blur(58.1px)',
                                        WebkitBackdropFilter: 'blur(58.1px)',
                                    }}
                                />
                                {errors.description && (
                                    <p className="px-1 text-xs text-red-400 leading-tight">
                                        {errors.description}
                                    </p>
                                )}
                            </div>

                            {/* Attachments - optional */}
                            <div className="space-y-2">
                                <label className="text-[13px]! font-bold leading-[19.5px]! text-primary-text/80">
                                    Attachments <span className="font-normal! text-primary-text/35!">— optional</span>
                                </label>

                                <input
                                    type="file"
                                    ref={fileInputRef}
                                    onChange={handleFileChange}
                                    accept="image/*,.pdf, video/*"
                                    className="hidden"
                                />

                                <div
                                    onClick={() => fileInputRef.current?.click()}
                                    className={`flex cursor-pointer flex-col items-center mt-2 justify-center rounded-2xl border border-dashed bg-transparent! p-6 text-center transition-all ${
                                        errors.attachments
                                            ? 'border-red-500/60 hover:border-red-400'
                                            : 'border-[#FFFFFF1f] hover:border-neutral-500'
                                    }`}
                                >
                                    <p className="text-[13px] leading-[19.5px]! text-primary-text/50">
                                        Drop images here or click to upload
                                    </p>
                                    <p className="mt-1 text-[11px] text-primary-text/28 leading-[16.5px]! font-normal">
                                        Video, PNG, JPG or PDF &bull; up to 10 MB each
                                    </p>
                                </div>

                                {errors.attachments && (
                                    <p className="px-1 text-xs text-red-400 leading-tight">
                                        {errors.attachments}
                                    </p>
                                )}

                                {/* Uploaded File List */}
                                {attachments.length > 0 && (
                                    <div className="flex flex-wrap gap-2 pt-2">
                                        {attachments.map((file, index) => (
                                            <div
                                                key={`${file.name}-${index}`}
                                                className="inline-flex items-center gap-2 rounded-full border border-[#FFFFFF1A] bg-primary-text/6! px-3 py-1 text-xs text-primary-text/70 leading-4.5!"
                                            >
                                                <span className="truncate max-w-38">{file.name}</span>
                                                <button
                                                    type="button"
                                                    onClick={() => removeAttachment(index)}
                                                    className="text-neutral-400 hover:text-white"
                                                >
                                                    <X className="size-3" />
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Submit Button */}
                            <div className="pt-2 space-y-4">
                                <PrimaryGlassBtn
                                    className='w-full!'
                                    type="submit"
                                    disabled={createTicketMutation.isPending}
                                >
                                    {createTicketMutation.isPending ? 'Sending...' : 'Send to Punk AI Support'}
                                </PrimaryGlassBtn>
                                <p className="mt-2 text-center text-xs text-primary-text/30 leading-4.5! font-normal">
                                    We&apos;ll reply to your email. Your ticket number arrives instantly.
                                </p>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </Box>
    );
}

