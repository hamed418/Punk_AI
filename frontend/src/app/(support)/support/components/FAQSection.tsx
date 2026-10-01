'use client';

import { Accordion, Box, Loader, Center } from '@mantine/core';
import { Minus, Plus, Search, SearchX } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useGetFaqCategories, useGetFaqs } from '../../../../hooks/api/useFaqApi';
import { FAQItem as ApiFAQItem } from '../../../../types/faq.types';

interface FAQItem {
    id: string;
    category: string;
    question: string;
    answer: string;
}

const COLORS = ['bg-orange-500', 'bg-pink-500', 'bg-blue-500', 'bg-emerald-400', 'bg-purple-500', 'bg-yellow-500'];

export default function FAQSection() {
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('Popular');
    const [value, setValue] = useState<string | null>(null);

    const { data: categoriesData, isLoading: categoriesLoading } = useGetFaqCategories();

    // Fetch all FAQs so category counts remain accurate across all categories
    const { data: faqsData, isLoading: faqsLoading } = useGetFaqs();

    const isLoading = categoriesLoading || faqsLoading;

    // Transform API FAQs to the format needed by the component
    const FAQ_DATA: FAQItem[] = useMemo(() => {
        if (!faqsData) return [];
        return faqsData.map((item: ApiFAQItem) => {
            const categoryName =
                item.category?.name ||
                categoriesData?.find((c) => c.id === item.category_id)?.name ||
                'Uncategorized';

            return {
                id: item.id,
                category: categoryName,
                question: item.question,
                answer: item.answer,
            };
        });
    }, [faqsData, categoriesData]);

    // Transform API Categories
    const CATEGORIES = useMemo(() => {
        if (!categoriesData) return [{ id: 'Popular', label: 'Popular' }];
        const cats = categoriesData.map(c => ({ id: c.name, label: c.name }));
        return [{ id: 'Popular', label: 'Popular' }, ...cats];
    }, [categoriesData]);

    // Compute category counts dynamically from FAQ_DATA
    const categoryCounts = useMemo(() => {
        const counts: Record<string, number> = { Popular: FAQ_DATA.length };
        FAQ_DATA.forEach((item) => {
            counts[item.category] = (counts[item.category] || 0) + 1;
        });
        return counts;
    }, [FAQ_DATA]);

    // Filtered FAQ items
    const filteredData = useMemo(() => {
        return FAQ_DATA.filter((item) => {
            const matchesSearch =
                item.question.toLowerCase().includes(searchQuery.toLowerCase()) ||
                item.answer.toLowerCase().includes(searchQuery.toLowerCase());

            const matchesCategory =
                selectedCategory === 'Popular' || item.category === selectedCategory;

            return matchesSearch && matchesCategory;
        });
    }, [FAQ_DATA, searchQuery, selectedCategory]);

    // Group by category for section headers
    const groupedData = useMemo(() => {
        if (!categoriesData) return [];
        const groups = categoriesData.map((cat, index) => {
            return {
                category: cat.name.toUpperCase(),
                color: COLORS[index % COLORS.length],
                items: filteredData.filter((i) => i.category === cat.name),
            };
        });

        // Add uncategorized if any
        const uncategorizedItems = filteredData.filter((i) => i.category === 'Uncategorized');
        if (uncategorizedItems.length > 0) {
            groups.push({
                category: 'UNCATEGORIZED',
                color: 'bg-gray-500',
                items: uncategorizedItems,
            });
        }

        return groups.filter((g) => g.items.length > 0);
    }, [filteredData, categoriesData]);

    if (isLoading) {
        return (
            <Center className="my-24">
                <Loader color="white" />
            </Center>
        );
    }

    return (
        <Box className="mx-auto my-12 max-w-375 px-4 md:px-8">
            {/* Header Row */}
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
                <h2 className="text-2xl font-semibold tracking-[-0.28px]! text-white sm:text-[28px]!">
                    Frequently asked
                </h2>
                <span className="text-xs text-neutral-400 font-normal">
                    {FAQ_DATA.length} answers &bull; Updated {new Date().toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}
                </span>
            </div>

            {/* Search Input */}
            <div className="relative mt-6">
                <Search className="pointer-events-none absolute left-5 top-1/2 z-10 size-4 -translate-y-1/2 text-primary-text sm:left-6" />
                <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search these questions — tokens, billing, refunds..."
                    className="w-full rounded-full border! border-[#FFFFFF1C]! bg-[#FFFFFF05]! py-2 pl-12 pr-5 text-[13.5px]! text-primary-text placeholder:text-primary-text/30 backdrop-blur-[58.1px] transition-all focus:border-white/30! focus:outline-none sm:py-3 sm:pl-14 sm:pr-6 sm:text-base"
                    style={{
                        backgroundColor: '#FFFFFF05',
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        backdropFilter: 'blur(58.1px)',
                        WebkitBackdropFilter: 'blur(58.1px)',
                    }}
                />
            </div>

            {/* Category Pills */}
            <div className="mt-4 flex flex-wrap gap-2">
                {CATEGORIES.map((cat) => {
                    const isSelected = selectedCategory === cat.id;
                    const count = categoryCounts[cat.id] || 0;
                    return (
                        <button
                            key={cat.id}
                            type="button"
                            onClick={() => setSelectedCategory(cat.id)}
                            className={` ${isSelected
                                ? 'text-primary-text font-medium'
                                : 'text-primary-text/55'
                                } hover:bg-primary-bg/2 hover:text-primary-text/80 light:backdrop-blur-2xl! prompt-tag-button! flex shrink-0 cursor-pointer items-center gap-1.5 rounded-[36px]! bg-white/1! px-3 py-1 text-[12.5px]! backdrop-blur-[12.7px]! transition-all`}
                            style={{
                                border: "solid 1px #FFFFFF12",
                                boxShadow: isSelected ? 'var(--shadow-new-chat-chip) !important' : 'none',
                            }}
                        >
                            <span>{cat.label}</span>
                            <span
                                className={`text-[10px] ${isSelected
                                    ? 'text-primary-text'
                                    : 'text-primary-text/55'
                                    } group-hover:text-primary-text/80`}
                            >
                                {count}
                            </span>
                        </button>
                    );
                })}
            </div>

            {/* Grouped Accordion Sections */}
            <div className="mt-10 space-y-8">
                {groupedData.length > 0 ? (
                    groupedData.map((group) => (
                        <div key={group.category} className="space-y-3">
                            {/* Category Subheader */}
                            <div className="flex items-center gap-2 border-b border-[#FFFFFF0D] pb-2">
                                <span className={`h-2 w-2 rounded-full ${group.color}`} />
                                <span className="text-xs font-semibold tracking-[0.84px]! text-primary-text/85! uppercase">
                                    {group.category}
                                </span>
                                <span className="ml-auto text-[11.5px]! text-primary-text/30">{group.items.length}</span>
                            </div>

                            {/* Mantine Accordion */}
                            <Accordion
                                value={value}
                                onChange={setValue}
                                variant="separated"
                                radius="xl"
                                chevron={null}
                                styles={{
                                    item: {
                                        backgroundColor: '#FFFFFF03',
                                        boxShadow:
                                            '0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',
                                        backdropFilter: 'blur(75.9px)',
                                    },
                                }}
                                className="space-y-1"
                            >
                                {group.items.map((item) => {
                                    const isOpen = value === item.id;
                                    return (
                                        <Accordion.Item key={item.id} value={item.id} className="p-1">
                                            <Accordion.Control>
                                                <div className="flex items-start justify-between gap-4">
                                                    <span className="font-medium text-primary-text text-[13.8px]! leading-[19.32px]!">
                                                        {item.question}
                                                    </span>
                                                    <div className="mt-0.5 shrink-0 text-neutral-400">
                                                        {isOpen ? <Minus className="size-4" /> : <Plus className="size-4" />}
                                                    </div>
                                                </div>
                                            </Accordion.Control>
                                            <Accordion.Panel className='text-sm text-primary-text/60 leading-[19.32px]!'>{item.answer}</Accordion.Panel>
                                        </Accordion.Item>
                                    );
                                })}
                            </Accordion>
                        </div>
                    ))
                ) : (
                    <div className="my-16 flex flex-col items-center justify-center text-center">
                        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-white/5 text-neutral-400">
                            <SearchX className="size-6 text-neutral-400" />
                        </div>
                        <h3 className="text-lg font-semibold text-white">No matching FAQs found</h3>
                        <p className="mt-1.5 max-w-md text-xs text-neutral-400 sm:text-sm">
                            {searchQuery
                                ? `We couldn't find any questions matching "${searchQuery}". Try searching for different keywords or clearing your filters.`
                                : 'No questions are available in this category.'}
                        </p>
                        {(searchQuery || selectedCategory !== 'Popular') && (
                            <button
                                type="button"
                                onClick={() => {
                                    setSearchQuery('');
                                    setSelectedCategory('Popular');
                                }}
                                className="mt-5 cursor-pointer rounded-full border border-white/14 bg-white/5 px-4 py-2 text-xs font-medium text-white backdrop-blur-md transition-all hover:bg-white/10"
                            >
                                Clear search & filters
                            </button>
                        )}
                    </div>
                )}
            </div>
        </Box>
    );
}