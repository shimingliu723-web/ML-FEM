#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sched.h>
typedef int (*dec_fn)(uint8_t*,const uint8_t*,const uint8_t*);
typedef void (*reset_fn)(void);
typedef void (*read_fn)(uint64_t*);
typedef void (*probe_fn)(int);
#define TRACE_STAGES 8
static uint64_t now(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC_RAW,&t))exit(3);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static uint32_t rnd(uint32_t*x){*x^=*x<<13;*x^=*x>>17;*x^=*x<<5;return *x;}
static uint64_t call(dec_fn f,uint8_t*ct,uint8_t*sk,uint8_t*buf,size_t n){uint8_t ss[32];memcpy(buf,ct,n);uint64_t a=now();int rc=f(ss,buf,sk);uint64_t b=now();if(rc)exit(4);return b-a;}
int main(int argc,char**v){
 if(argc!=9)return 2;
 int level=atoi(v[3]),pairs=atoi(v[5]),cls=atoi(v[8]);
 size_t sk=level==512?1632:level==768?2400:3168,ct=level==512?768:level==768?1088:1568;
 if((level!=512&&level!=768&&level!=1024)||pairs<100||pairs>100000||cls<1||cls>3)return 2;
 uint32_t seed=strtoul(v[6],NULL,10),count=0; if(!seed)seed=1;
 FILE*in=fopen(v[4],"rb");if(!in||fread(&count,4,1,in)!=1||!count||count>4096)return 2;
 size_t row=sk+4*ct,size=count*row;uint8_t*data=malloc(size),*buf=NULL;
 if(!data||fread(data,1,size,in)!=size||fgetc(in)!=EOF||posix_memalign((void**)&buf,64,ct))return 2;fclose(in);
 void*h[2]={dlopen(v[1],RTLD_NOW|RTLD_LOCAL),dlopen(v[2],RTLD_NOW|RTLD_LOCAL)};
 if(!h[0]||!h[1])return 3;
 dec_fn dec[2];reset_fn reset;read_fn read_trace;
 for(int i=0;i<2;i++){*(void**)&dec[i]=dlsym(h[i],"mlkem_dec");if(!dec[i])return 3;}
 *(void**)&reset=dlsym(h[1],"mlkem_trace_reset");*(void**)&read_trace=dlsym(h[1],"mlkem_trace_read");if(!reset||!read_trace)return 3;
 probe_fn begin,end;*(void**)&begin=dlsym(h[1],"mlkem_trace_begin");*(void**)&end=dlsym(h[1],"mlkem_trace_end");if(!begin||!end)return 3;
 char calibration_path[4096];if(snprintf(calibration_path,sizeof(calibration_path),"%s.probes.csv",v[7])>=(int)sizeof(calibration_path))return 2;
 FILE*cal=fopen(calibration_path,"w");if(!cal)return 2;fputs("index,empty_ns,probe_pairs_ns,cpu\n",cal);
 for(int i=-100;i<1000;i++){uint64_t a=now(),b=now();reset();uint64_t c=now();for(int j=0;j<TRACE_STAGES;j++){begin(j);end(j);}uint64_t d=now();if(i>=0)fprintf(cal,"%d,%llu,%llu,%d\n",i,(unsigned long long)(b-a),(unsigned long long)(d-c),sched_getcpu());}if(fclose(cal))return 2;
 FILE*out=fopen(v[7],"w");if(!out)return 2;
 fputs("pair,sample,order,valid_impl_order,changed_impl_order,original_valid_ns,original_changed_ns,instrumented_valid_ns,instrumented_changed_ns",out);
 for(int c=0;c<2;c++)for(int s=0;s<TRACE_STAGES;s++)fprintf(out,",%s_stage_%d",c?"changed":"valid",s);fputs(",cpu\n",out);
 for(int i=-2000;i<pairs;i++){
  uint32_t j=rnd(&seed)%count,order=rnd(&seed)&1,io[2]={rnd(&seed)&1,rnd(&seed)&1};
  uint8_t*p=data+j*row;uint64_t totals[2][2],stages[2][TRACE_STAGES];
  for(int k=0;k<2;k++){int c=k^order;uint8_t*input=p+sk+(c?cls:0)*ct;
   for(int m=0;m<2;m++){int impl=m^io[c];if(impl)reset();totals[impl][c]=call(dec[impl],input,p,buf,ct);if(impl)read_trace(stages[c]);}
  }
  if(i<0)continue;
  fprintf(out,"%d,%u,%u,%u,%u,%llu,%llu,%llu,%llu",i,j,order,io[0],io[1],(unsigned long long)totals[0][0],(unsigned long long)totals[0][1],(unsigned long long)totals[1][0],(unsigned long long)totals[1][1]);
  for(int c=0;c<2;c++)for(int s=0;s<TRACE_STAGES;s++)fprintf(out,",%llu",(unsigned long long)stages[c][s]);fprintf(out,",%d\n",sched_getcpu());
 }
 int rc=fclose(out);volatile uint8_t*w=data;for(size_t i=0;i<size;i++)w[i]=0;free(data);free(buf);dlclose(h[0]);dlclose(h[1]);return rc!=0;
}
