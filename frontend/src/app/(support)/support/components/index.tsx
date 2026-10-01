import { Box } from '@mantine/core';
import Banner from './Banner';
import FAQSection from './FAQSection';
import SupportCard from './SupportCard';

function SupportPageContent() {
    return (
        <Box>
            <Banner />
            <FAQSection />
            <SupportCard />
        </Box>
    );
}

export default SupportPageContent;