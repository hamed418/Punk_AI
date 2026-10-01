'use client';

import { useEffect, useState } from 'react';
import { Box, Loader, Select, Table, Text } from '@mantine/core';
import { metaFormLeadsAction, metaLeadFormsAction } from '@/actions/connect.actions';
import type { MetaLead, MetaLeadForm } from '@/lib/api/connect';

/**
 * The leads Meta collected on the user's instant forms, inside Punk.
 *
 * A lead campaign delivers into Meta; without this the user leaves Punk to see the
 * thing they paid for. Meta's Lead Center stays the system of record — this is
 * visibility, so there is no export and no paging beyond the route's limit.
 *
 * Renders nothing when the user has no instant forms. A failed leads read is
 * shown, never turned into an empty table: "no leads yet" and "leads permission
 * missing" look identical otherwise, and the second never fixes itself.
 */
export default function MetaLeads() {
  const [forms, setForms] = useState<MetaLeadForm[] | null>(null);
  const [formId, setFormId] = useState<string | null>(null);
  const [leads, setLeads] = useState<MetaLead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    metaLeadFormsAction().then((result) => {
      if (live) setForms(result.success && result.data ? result.data : []);
    });
    return () => {
      live = false;
    };
  }, []);

  const pick = async (id: string | null) => {
    setFormId(id);
    setLeads(null);
    setError(null);
    const form = forms?.find((f) => f.id === id);
    if (!form) return;
    const result = await metaFormLeadsAction(form.id, form.page_id);
    if (result.success && result.data) setLeads(result.data);
    else setError(result.error ?? 'Failed to load leads.');
  };

  if (!forms) {
    return (
      <Box className="flex items-center justify-center py-8 gap-2 text-sm text-[#FAF9F599]">
        <Loader size="xs" /> Loading instant forms...
      </Box>
    );
  }

  if (!forms.length) {
    return (
      <Box className="flex flex-col items-center justify-center py-8 text-center gap-2">
        <Text fz={14} fw={600} className="text-primary-text">
          No Instant Forms Found
        </Text>
        <Text fz={12} className="text-[#FAF9F580] max-w-sm">
          No instant lead forms were found for this Meta connection. Create a form in Meta Ads Manager to view leads here.
        </Text>
      </Box>
    );
  }

  // Union of every answer's question, in first-seen order — forms are free-form.
  const columns = Array.from(new Set((leads ?? []).flatMap((l) => Object.keys(l.fields))));

  return (
    <Box className="flex flex-col gap-3">
      <Box className="flex flex-col gap-1">
        <Text fz={13} fw={600} className="text-primary-text">
          Select Form
        </Text>
        <Text fz={12} className="text-[#FAF9F566]">
          Choose an instant lead form to view submitted leads.
        </Text>
      </Box>
      <Select
        placeholder="Choose an instant form"
        value={formId}
        onChange={pick}
        searchable
        maxDropdownHeight={200}
        data={forms.map((f) => ({
          value: f.id,
          label: `${f.name ?? f.id}${f.page_name ? ` — ${f.page_name}` : ''}`,
        }))}
        comboboxProps={{
          withinPortal: true,
          zIndex: 1000000,
          position: 'bottom',
          width: 'target',
          middlewares: { flip: false, shift: true },
        }}
        styles={{
          input: {
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          },
          option: {
            whiteSpace: 'normal',
            wordBreak: 'break-word',
            lineHeight: '1.4',
          },
          dropdown: {
            maxWidth: '100%',
            overflowX: 'hidden',
          },
        }}
      />
      {error && (
        <Text fz={12} className="text-red-300">
          {error}
        </Text>
      )}
      {formId && !error && !leads && (
        <Box className="flex items-center justify-center py-6 gap-2 text-sm text-[#FAF9F599]">
          <Loader size="xs" /> Loading leads...
        </Box>
      )}
      {leads && !leads.length && (
        <Box className="rounded-xl border border-[#FFFFFF14] bg-[#FFFFFF05] p-6 text-center">
          <Text fz={12} className="text-[#FAF9F566]">
            No leads captured on this form yet.
          </Text>
        </Box>
      )}
      {leads && leads.length > 0 && (
        <Box className="overflow-x-auto rounded-xl border border-[#FFFFFF14]">
          <Table fz={12} verticalSpacing="sm" horizontalSpacing="md">
            <Table.Thead className="bg-[#FFFFFF0A]">
              <Table.Tr>
                <Table.Th className="text-[#FAF9F580] whitespace-nowrap">Received</Table.Th>
                {columns.map((c) => (
                  <Table.Th key={c} className="text-[#FAF9F580] whitespace-nowrap">{c}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {leads.map((lead) => (
                <Table.Tr key={lead.id} className="border-b border-[#FFFFFF0A] hover:bg-[#FFFFFF05]">
                  <Table.Td className="text-[#FAF9F5B3] whitespace-nowrap">
                    {lead.created_time ? new Date(lead.created_time).toLocaleString() : ''}
                  </Table.Td>
                  {columns.map((c) => (
                    <Table.Td key={c} className="text-primary-text">
                      {lead.fields[c] ?? ''}
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Box>
      )}
    </Box>
  );
}
