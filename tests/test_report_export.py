from ares.report_export import export_markdown


def test_legacy_report_does_not_imply_model_validation():
    result=export_markdown('# Saved report',{'citations':[]},[])
    assert result.startswith('# Saved report')
    assert 'Local reasoning status: not recorded' in result
    assert 'not scientific truth' in result


def test_export_keeps_failures_and_unvalidated_proposals_visible():
    payload={'reasoner':{'status':'rejected','reason':'Output budget exhausted'},
             'critique':{'rejected_proposals':[{'candidate':{'statement':'Adhesion increased'},
                          'check':{'reasons':['Direction opposes observation']}}]},
             'hypotheses':[{'statement':'Test replication','citation':'S1','basis_quote':'Adhesion decreased',
                            'mechanism':'Unverified mechanism','falsification':'Controlled comparison',
                            'consistency_check':{'direction_check':{'status':'requires_review'},
                                                 'limitations':['Outcomes not aligned']}}]}
    result=export_markdown('# Saved report',payload,[])
    for text in ['Output budget exhausted','Rejected model proposal','Direction opposes observation',
                 'Test replication','Evidence citation: S1','Adhesion decreased','Unverified mechanism',
                 'Controlled comparison','requires_review','Outcomes not aligned','not scientific approval']:
        assert text in result
    assert export_markdown('# Saved report',payload,[])==result
