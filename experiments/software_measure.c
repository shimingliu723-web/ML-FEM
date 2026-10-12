#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
#include <sched.h>
#include <sys/resource.h>

typedef int (*dec_fn)(uint8_t *, const uint8_t *, const uint8_t *);
static uint64_t now(void) { struct timespec t; if(clock_gettime(CLOCK_MONOTONIC_RAW,&t)) exit(3); return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec; }
static uint32_t rnd(uint32_t *x) { *x^=*x<<13; *x^=*x>>17; *x^=*x<<5; return *x; }
static uint64_t measure(dec_fn f,uint8_t *ss,const uint8_t *ct,uint8_t *sk,uint8_t *staging,size_t n) {
  /* Equalize public input address and cache preparation outside the timed call. */
  memcpy(staging,ct,n);
  uint64_t a=now(); int rc=f(ss,staging,sk); uint64_t b=now(); if(rc) exit(4); return b-a;
}
int main(int argc,char **argv) {
  if(argc==3 && !strcmp(argv[1],"--probe")) {
    FILE *o=fopen(argv[2],"w"); if(!o) return 2;
    fputs("index,empty_ns,work_ns,cpu\n",o);
    volatile uint32_t value=1234567;
    for(int i=-100;i<1000;i++) { uint64_t a=now(),b=now(),c=now(); for(int j=0;j<4000;j++) value=value*1664525U+1013904223U; uint64_t d=now(); if(i>=0) fprintf(o,"%d,%llu,%llu,%d\n",i,(unsigned long long)(b-a),(unsigned long long)(d-c),sched_getcpu()); }
    return fclose(o)!=0;
  }
  if(argc!=8) { fprintf(stderr,"usage: software_measure LIB LEVEL SAMPLE.bin PAIRS SEED OUTPUT.csv CLASS(1..3)\n"); return 2; }
  int level=atoi(argv[2]),cls=atoi(argv[7]);
  size_t skn=0,ctn=0;
  if(level==512){skn=1632;ctn=768;} else if(level==768){skn=2400;ctn=1088;} else if(level==1024){skn=3168;ctn=1568;} else return 2;
  if(cls<1 || cls>3) return 2;
  int pairs=atoi(argv[4]); if(pairs<100 || pairs>100000) return 2;
  uint32_t seed=(uint32_t)strtoul(argv[5],NULL,10); if(!seed) seed=1;
  FILE *in=fopen(argv[3],"rb"); if(!in) return 2;
  uint32_t count=0; if(fread(&count,4,1,in)!=1 || count<1 || count>4096) return 2;
  size_t row=skn+4*ctn, size=count*row;
  uint8_t *data=malloc(size); if(!data || fread(data,1,size,in)!=size || fgetc(in)!=EOF) return 2; fclose(in);
  void *lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL); if(!lib){fprintf(stderr,"library load failed\n"); return 3;}
  dec_fn dec; *(void **)(&dec)=dlsym(lib,"mlkem_dec"); if(!dec) return 3;
  uint8_t ss[32];
  uint8_t *staging=NULL;
  if(posix_memalign((void **)&staging,64,ctn)!=0) return 2;
  for(int i=0;i<2000;i++){uint8_t *p=data+(i%count)*row; measure(dec,ss,p+skn,p,staging,ctn); measure(dec,ss,p+skn+cls*ctn,p,staging,ctn);}
  FILE *o=fopen(argv[6],"w"); if(!o) return 2;
  fputs("pair,sample,order,valid_ns,changed_ns,cpu\n",o);
  for(int i=0;i<pairs;i++){
    uint32_t j=rnd(&seed)%count,order=rnd(&seed)&1; uint8_t *p=data+j*row;
    uint64_t a,b;
    if(order==0){a=measure(dec,ss,p+skn,p,staging,ctn); b=measure(dec,ss,p+skn+cls*ctn,p,staging,ctn);}
    else {b=measure(dec,ss,p+skn+cls*ctn,p,staging,ctn); a=measure(dec,ss,p+skn,p,staging,ctn);}
    fprintf(o,"%d,%u,%u,%llu,%llu,%d\n",i,j,order,(unsigned long long)a,(unsigned long long)b,sched_getcpu());
  }
  int result=fclose(o)!=0; volatile uint8_t *wipe=data; for(size_t i=0;i<size;i++) wipe[i]=0; free(staging); free(data); dlclose(lib); return result;
}
