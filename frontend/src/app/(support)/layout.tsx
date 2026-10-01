import SupportLayout from '@/layouts/supportLayout/SupportLayout';
import React from 'react';


const SupportPageLayout = ({ children }: { children: React.ReactNode }) => {
    return (
        <SupportLayout>
            {children}
        </SupportLayout>
    );
};

export default SupportPageLayout;