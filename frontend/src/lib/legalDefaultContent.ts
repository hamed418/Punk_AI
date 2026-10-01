export interface LegalSection {
  id: string;
  eyebrow?: string;
  title: string;
  content: string[]; // array of paragraphs or HTML snippets
  listItems?: string[];
  extraContent?: string[];
}

export interface DefaultLegalDoc {
  docType: 'Terms of Service' | 'Privacy Policy';
  badge: string;
  title: string;
  lastUpdated: string;
  description: string;
  sections: LegalSection[];
}

export const DEFAULT_TERMS_OF_SERVICE: DefaultLegalDoc = {
  docType: 'Terms of Service',
  badge: 'LEGAL',
  title: 'Terms and Conditions',
  lastUpdated: 'August 2026',
  description: 'Please read these terms carefully before using Punk AI. Last updated August 2026.',
  sections: [
    {
      id: 'acceptance-of-terms',
      eyebrow: 'ACCEPTANCE OF TERMS',
      title: 'Acceptance of Terms',
      content: [
        'By accessing or using Punk AI ("the Service"), you agree to be bound by these Terms and Conditions ("Terms"). If you do not agree with any part of these Terms, you may not use the Service.',
        'These Terms apply to all users of the Service, including visitors, registered users, and subscribers. Your continued use of the Service after any modifications to these Terms constitutes acceptance of those changes.',
      ],
    },
    {
      id: 'use-of-service',
      eyebrow: 'USE OF SERVICE',
      title: 'Use of Service',
      content: [
        'Punk AI grants you a limited, non-exclusive, non-transferable, revocable license to use the Service for personal or internal business purposes, subject to these Terms.',
        'You agree not to:',
      ],
      listItems: [
        'Use the Service to generate content that is illegal, harmful, threatening, abusive, harassing, or defamatory',
        'Attempt to reverse-engineer, decompile, or extract source code from any part of the Service',
        'Use automated tools, bots, or scripts to access the Service at scale without prior written consent',
        'Misrepresent yourself or your affiliation with any person or organization',
        'Share account credentials or allow unauthorized third parties to access your account',
        'Circumvent, disable, or interfere with security features of the Service',
      ],
    },
    {
      id: 'account-registration',
      eyebrow: 'ACCOUNT REGISTRATION',
      title: 'Account Registration',
      content: [
        'To access certain features of the Service, you must create an account. When registering, you agree to provide accurate, current, and complete information. You are responsible for maintaining the confidentiality of your account credentials and for all activity that occurs under your account.',
        'You must notify Punk AI immediately at <strong class="text-white font-medium">support@punkai.com</strong> if you suspect unauthorized access to your account. Punk AI will not be liable for any loss or damage resulting from your failure to comply with this obligation.',
        'Accounts may only be created by individuals who are 13 years of age or older. If you are under 18, you represent that you have obtained parental or guardian consent.',
      ],
    },
    {
      id: 'payments-billing',
      eyebrow: 'PAYMENTS & BILLING',
      title: 'Payments & Billing',
      content: [
        'Certain features of the Service may require payment of fees. All fees are stated in US Dollars and are non-refundable except as required by law or explicitly stated in these Terms.',
        'Subscription plans automatically renew at the end of each billing cycle unless cancelled prior to renewal. You may cancel your subscription at any time through your account settings.',
        'We reserve the right to adjust pricing at any time. Any price changes will be communicated to you at least 30 days before they take effect.',
      ],
    },
    {
      id: 'intellectual-property',
      eyebrow: 'INTELLECTUAL PROPERTY',
      title: 'Intellectual Property',
      content: [
        'The Service and its original content, features, functionality, trademarks, service marks, and logos are owned by Punk AI and are protected by international copyright, trademark, and other intellectual property laws.',
        'Punk AI does not claim ownership over the prompts or inputs you submit to the Service. Subject to these Terms, you retain all rights to your inputs and the outputs generated specifically for you by the Service.',
      ],
    },
    {
      id: 'user-content',
      eyebrow: 'USER CONTENT',
      title: 'User Content',
      content: [
        'You are solely responsible for the content you submit, upload, or transmit through the Service ("User Content"). You represent and warrant that you own or have obtained all necessary rights to your User Content.',
        'By submitting User Content, you grant Punk AI a worldwide, non-exclusive, royalty-free license to use, process, and store your User Content solely to the extent necessary to provide, maintain, and improve the Service.',
      ],
    },
    {
      id: 'privacy',
      eyebrow: 'PRIVACY',
      title: 'Privacy',
      content: [
        'Your privacy is critically important to us. Please review our Privacy Policy, which also governs your use of the Service, to understand our data collection, use, and protection practices.',
      ],
    },
    {
      id: 'disclaimers',
      eyebrow: 'DISCLAIMERS',
      title: 'Disclaimers',
      content: [
        'The Service is provided on an "AS IS" and "AS AVAILABLE" basis without warranties of any kind, whether express or implied, including but not limited to implied warranties of merchantability, fitness for a particular purpose, non-infringement, or course of performance.',
        'Punk AI does not warrant that the Service will be uninterrupted, secure, error-free, or free of viruses or other harmful components.',
      ],
    },
    {
      id: 'limitation-of-liability',
      eyebrow: 'LIMITATION OF LIABILITY',
      title: 'Limitation of Liability',
      content: [
        'In no event shall Punk AI, its directors, employees, partners, agents, suppliers, or affiliates be liable for any indirect, incidental, special, consequential, or punitive damages, including loss of profits, data, use, goodwill, or other intangible losses, resulting from your access to or use of or inability to access or use the Service.',
        'In no event shall Punk AI\'s total aggregate liability exceed the amount paid by you to Punk AI in the twelve (12) months preceding the claim, or $100, whichever is greater.',
      ],
    },
    {
      id: 'termination',
      eyebrow: 'TERMINATION',
      title: 'Termination',
      content: [
        'We may terminate or suspend your account and access to the Service immediately, without prior notice or liability, for any reason whatsoever, including without limitation if you breach these Terms.',
        'Upon termination, your right to use the Service will immediately cease. If you wish to terminate your account, you may simply discontinue using the Service or delete your account through your profile settings.',
      ],
    },
    {
      id: 'changes-to-terms',
      eyebrow: 'CHANGES TO TERMS',
      title: 'Changes to Terms',
      content: [
        'We reserve the right, at our sole discretion, to modify or replace these Terms at any time. If a revision is material, we will provide at least 30 days notice prior to any new terms taking effect.',
        'What constitutes a material change will be determined at our sole discretion. By continuing to access or use our Service after any revisions become effective, you agree to be bound by the revised terms.',
      ],
    },
    {
      id: 'contact-us',
      eyebrow: 'CONTACT US',
      title: 'Contact Us',
      content: [
        'If you have any questions about these Terms, please contact our legal and support team at <strong class="text-white font-medium">support@punkai.com</strong>.',
      ],
    },
  ],
};

export const DEFAULT_PRIVACY_POLICY: DefaultLegalDoc = {
  docType: 'Privacy Policy',
  badge: 'LEGAL',
  title: 'Privacy Policy',
  lastUpdated: 'August 2026',
  description: 'Learn how we collect, protect, process, and use your personal information and data.',
  sections: [
    {
      id: 'information-we-collect',
      eyebrow: 'INFORMATION WE COLLECT',
      title: 'Information We Collect',
      content: [
        'We collect information you provide directly to us when registering an account, configuring your profile, interacting with our AI services, and communicating with customer support.',
        'This information may include your name, email address, payment details, workspace preferences, and chat or prompt logs entered into the Service.',
      ],
    },
    {
      id: 'how-we-use-information',
      eyebrow: 'HOW WE USE INFORMATION',
      title: 'How We Use Your Information',
      content: [
        'We use the information we collect to operate, deliver, and continuously enhance Punk AI and its underlying features.',
        'Key purposes include:',
      ],
      listItems: [
        'Providing, maintaining, and improving our AI generation and collaboration platform',
        'Processing transactions, subscription renewals, and sending related invoices',
        'Responding to customer inquiries, support tickets, and technical issue reports',
        'Detecting, preventing, and addressing fraudulent activities, unauthorized access, or abuse',
        'Personalizing user experience and analyzing platform performance metrics',
      ],
    },
    {
      id: 'data-sharing-third-parties',
      eyebrow: 'DATA SHARING & THIRD PARTIES',
      title: 'Data Sharing & Third Parties',
      content: [
        'We do not sell, rent, or trade your personal data to third parties for marketing purposes.',
        'We may share data with trusted third-party service providers who assist us in operating our services, hosting infrastructure, processing payments, and conducting system monitoring under strict data confidentiality agreements.',
      ],
    },
    {
      id: 'cookies-tracking',
      eyebrow: 'COOKIES & TRACKING',
      title: 'Cookies & Tracking Technologies',
      content: [
        'We use cookies, local storage tokens, and similar tracking mechanisms to maintain authentication state, remember your theme and preferences, and analyze aggregate traffic trends.',
        'You can configure your browser to reject cookies, though certain interactive features of the application may not function as intended without them.',
      ],
    },
    {
      id: 'data-security',
      eyebrow: 'DATA SECURITY',
      title: 'Data Security',
      content: [
        'We employ robust technical and organizational security measures designed to safeguard your personal information from unauthorized access, loss, misuse, or alteration.',
        'All data in transit is protected using industry-standard TLS encryption, and sensitive assets are stored securely on encrypted cloud storage clusters.',
      ],
    },
    {
      id: 'your-rights-choices',
      eyebrow: 'YOUR RIGHTS & CHOICES',
      title: 'Your Rights & Choices',
      content: [
        'Depending on your jurisdiction, you may have rights regarding your personal information, including the right to access, correct, export, or request deletion of your personal data.',
        'You can exercise these rights at any time by navigating to your account settings or emailing our privacy team directly.',
      ],
    },
    {
      id: 'data-retention',
      eyebrow: 'DATA RETENTION',
      title: 'Data Retention',
      content: [
        'We retain your personal data only for as long as necessary to fulfill the purposes outlined in this Privacy Policy, comply with legal obligations, resolve disputes, and enforce our agreements.',
      ],
    },
    {
      id: 'childrens-privacy',
      eyebrow: 'CHILDREN\'S PRIVACY',
      title: 'Children\'s Privacy',
      content: [
        'Our Service is not directed to individuals under the age of 13. We do not knowingly collect personal information from children under 13. If you believe a child has provided us with personal information, please contact us immediately.',
      ],
    },
    {
      id: 'changes-to-policy',
      eyebrow: 'CHANGES TO THIS POLICY',
      title: 'Changes to This Policy',
      content: [
        'We may update our Privacy Policy periodically to reflect changes in our practices or legal requirements. We will notify you of any significant revisions by posting the updated policy on this page with a revised date.',
      ],
    },
    {
      id: 'contact-us',
      eyebrow: 'CONTACT US',
      title: 'Contact Us',
      content: [
        'If you have questions, concerns, or requests regarding this Privacy Policy or our data handling practices, please contact us at <strong class="text-white font-medium">support@punkai.com</strong>.',
      ],
    },
  ],
};
